use open_aio_core::{
    signalrgb_jpeg_header, UsbTransport, CHUNK_SIZE, CMD_SIGNALRGB_BENCH_DISCARD,
    CMD_SIGNALRGB_BENCH_RX, CMD_SIGNALRGB_FLUSH, CMD_SIGNALRGB_JPEG, CMD_SIGNALRGB_RGB565_FRAME,
    CMD_SIGNALRGB_RGB565_RECT, IN_ENDPOINT, OUT_ENDPOINT, PID, VID,
};
use std::env;
use std::fs;
use std::io::{self, ErrorKind, Read, Write};
use std::process;

const STDIO_MAGIC: &[u8; 4] = b"OAIO";
const STDIO_HEADER_LEN: usize = 10;
const STDIO_CMD_JPEG: u8 = 0x01;
const STDIO_CMD_RGB565_RECT: u8 = 0x02;
const STDIO_CMD_FLUSH: u8 = 0x03;
const STDIO_CMD_RGB565_FRAME: u8 = 0x04;
const STDIO_MAX_PAYLOAD: usize = 512 * 1024;

fn main() {
    let mut args = env::args().skip(1);
    let command = args.next().unwrap_or_else(|| "help".to_string());

    let result = match command.as_str() {
        "health" => {
            println!("{{\"ok\":true,\"service\":\"open-aio-service\"}}");
            Ok(())
        }
        "protocol-info" => {
            println!(
                "{{\"vid\":{},\"pid\":{},\"outEndpoint\":{},\"inEndpoint\":{},\"chunkSize\":{},\"jpegCommand\":{},\"rgb565RectCommand\":{},\"flushCommand\":{},\"rgb565FrameCommand\":{},\"benchRxCommand\":{},\"benchDiscardCommand\":{}}}",
                VID, PID, OUT_ENDPOINT, IN_ENDPOINT, CHUNK_SIZE, CMD_SIGNALRGB_JPEG, CMD_SIGNALRGB_RGB565_RECT, CMD_SIGNALRGB_FLUSH, CMD_SIGNALRGB_RGB565_FRAME, CMD_SIGNALRGB_BENCH_RX, CMD_SIGNALRGB_BENCH_DISCARD
            );
            Ok(())
        }
        "packet-info" => {
            if let Some(path) = args.next() {
                packet_info(&path)
            } else {
                fail("packet-info requires a JPEG file path")
            }
        }
        "send-jpeg" => {
            if let Some(path) = args.next() {
                send_jpeg(&path)
            } else {
                fail("send-jpeg requires a JPEG file path")
            }
        }
        "bench-rx" => {
            let bytes = args
                .next()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(64 * 1024);
            let frames = args
                .next()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(30);
            bench_rx(bytes, frames, true)
        }
        "bench-rx-nowait" => {
            let bytes = args
                .next()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(64 * 1024);
            let frames = args
                .next()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(30);
            bench_rx(bytes, frames, false)
        }
        "bench-rx-discard" => {
            let bytes = args
                .next()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(64 * 1024);
            let frames = args
                .next()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(30);
            bench_rx_discard(bytes, frames)
        }
        "stdio" => run_stdio(),
        "help" | "--help" | "-h" => {
            print_help();
            Ok(())
        }
        _ => fail(&format!("unknown command: {command}")),
    };

    if result.is_err() {
        process::exit(1);
    }
}

fn run_stdio() -> Result<(), ()> {
    let mut stdin = io::stdin().lock();
    let mut stdout = io::stdout().lock();
    let mut usb = UsbTransport::new();
    let mut header = [0_u8; STDIO_HEADER_LEN];
    let mut frame_id: u64 = 0;

    loop {
        match stdin.read_exact(&mut header) {
            Ok(()) => {}
            Err(error) if error.kind() == ErrorKind::UnexpectedEof => return Ok(()),
            Err(error) => {
                write_json_line(
                    &mut stdout,
                    &format!(
                        "{{\"ok\":false,\"status\":\"read_failed\",\"error\":\"{}\"}}",
                        json_escape(&error.to_string())
                    ),
                )?;
                return Err(());
            }
        }
        if &header[0..4] != STDIO_MAGIC {
            write_json_line(
                &mut stdout,
                "{\"ok\":false,\"status\":\"bad_magic\",\"error\":\"invalid stdio packet magic\"}",
            )?;
            return Err(());
        }

        let command = header[4];
        let flags = header[5];
        let len = u32::from_le_bytes([header[6], header[7], header[8], header[9]]) as usize;
        if (command != STDIO_CMD_FLUSH && len == 0) || len > STDIO_MAX_PAYLOAD {
            write_json_line(
                &mut stdout,
                &format!(
                    "{{\"ok\":false,\"status\":\"bad_length\",\"bytes\":{}}}",
                    len
                ),
            )?;
            continue;
        }

        let mut payload = vec![0_u8; len];
        if let Err(error) = stdin.read_exact(&mut payload) {
            write_json_line(
                &mut stdout,
                &format!(
                    "{{\"ok\":false,\"status\":\"payload_read_failed\",\"error\":\"{}\"}}",
                    json_escape(&error.to_string())
                ),
            )?;
            return Err(());
        }

        frame_id += 1;
        match command {
            STDIO_CMD_JPEG => {
                let result = usb.send_signalrgb_jpeg(&payload, flags);
                write_result(&mut stdout, frame_id, result)?;
            }
            STDIO_CMD_RGB565_RECT => {
                if payload.len() < 8 {
                    write_json_line(
                        &mut stdout,
                        &format!(
                            "{{\"ok\":false,\"id\":{},\"status\":\"bad_rect\",\"error\":\"rect payload missing header\"}}",
                            frame_id
                        ),
                    )?;
                    continue;
                }
                let x = u16::from_le_bytes([payload[0], payload[1]]);
                let y = u16::from_le_bytes([payload[2], payload[3]]);
                let width = u16::from_le_bytes([payload[4], payload[5]]);
                let height = u16::from_le_bytes([payload[6], payload[7]]);
                let result = usb.send_signalrgb_rgb565_rect(x, y, width, height, &payload[8..], flags);
                write_result(&mut stdout, frame_id, result)?;
            }
            STDIO_CMD_FLUSH => {
                let result = usb.flush_signalrgb_frame((flags & 0x80) != 0);
                write_result(&mut stdout, frame_id, result)?;
            }
            STDIO_CMD_RGB565_FRAME => {
                let result = usb.send_signalrgb_rgb565_frame(&payload, flags);
                write_result(&mut stdout, frame_id, result)?;
            }
            _ => {
                write_json_line(
                    &mut stdout,
                    &format!(
                        "{{\"ok\":false,\"id\":{},\"status\":\"bad_command\",\"command\":{}}}",
                        frame_id, command
                    ),
                )?;
            }
        }
    }
}

fn write_result(stdout: &mut impl Write, frame_id: u64, result: open_aio_core::UsbWriteResult) -> Result<(), ()> {
    write_json_line(
        stdout,
        &format!(
            "{{\"ok\":{},\"id\":{},\"status\":\"{}\",\"bytes\":{},\"writeMs\":{:.3},\"deviceStatus\":{},\"rxMs\":{},\"decodeMs\":{},\"flushMs\":{},\"error\":{}}}",
            result.ok,
            frame_id,
            json_escape(&result.status),
            result.bytes,
            result.write_ms,
            optional_json_u32(result.device_status),
            optional_json_u32(result.rx_ms),
            optional_json_u32(result.decode_ms),
            optional_json_u32(result.flush_ms),
            optional_json_string(result.error.as_deref())
        ),
    )
}

fn packet_info(path: &str) -> Result<(), ()> {
    let jpeg = read_file(path)?;
    match signalrgb_jpeg_header(&jpeg, 0, false) {
        Ok(header) => {
            println!(
                "{{\"ok\":true,\"bytes\":{},\"headerBytes\":{},\"magic\":\"{}\",\"command\":{}}}",
                jpeg.len(),
                header.len(),
                String::from_utf8_lossy(&header[0..4]),
                header[4]
            );
            Ok(())
        }
        Err(error) => fail(&error),
    }
}

fn send_jpeg(path: &str) -> Result<(), ()> {
    let jpeg = read_file(path)?;
    let mut usb = UsbTransport::new();
    let result = usb.send_signalrgb_jpeg(&jpeg, 0);
    println!(
        "{{\"ok\":{},\"status\":\"{}\",\"bytes\":{},\"writeMs\":{:.3},\"error\":{}}}",
        result.ok,
        json_escape(&result.status),
        result.bytes,
        result.write_ms,
        optional_json_string(result.error.as_deref())
    );
    if result.ok {
        Ok(())
    } else {
        Err(())
    }
}

fn bench_rx(bytes: usize, frames: usize, wait_status: bool) -> Result<(), ()> {
    if bytes == 0 || bytes > STDIO_MAX_PAYLOAD || frames == 0 {
        return fail("bench-rx requires bytes 1..524288 and frames > 0");
    }
    let mut payload = vec![0_u8; bytes];
    for (index, byte) in payload.iter_mut().enumerate() {
        *byte = (index as u8).wrapping_mul(31).wrapping_add(17);
    }

    let mut usb = UsbTransport::new();
    let started = std::time::Instant::now();
    let mut ok_frames = 0_usize;
    let mut write_ms_total = 0.0_f64;
    let mut rx_ms_total = 0_u64;
    let mut last_error: Option<String> = None;

    for _ in 0..frames {
        let result = usb.send_signalrgb_bench_rx(&payload, wait_status);
        write_ms_total += result.write_ms;
        if result.ok {
            ok_frames += 1;
            rx_ms_total += result.rx_ms.unwrap_or(0) as u64;
        } else {
            last_error = result.error;
            break;
        }
    }

    let elapsed_ms = started.elapsed().as_secs_f64() * 1000.0;
    let total_bytes = ok_frames * bytes;
    let mbps = if elapsed_ms > 0.0 {
        (total_bytes as f64 * 8.0) / (elapsed_ms / 1000.0) / 1_000_000.0
    } else {
        0.0
    };
    let mib_s = if elapsed_ms > 0.0 {
        (total_bytes as f64 / 1_048_576.0) / (elapsed_ms / 1000.0)
    } else {
        0.0
    };
    println!(
        "{{\"ok\":{},\"waitStatus\":{},\"bytesPerFrame\":{},\"frames\":{},\"okFrames\":{},\"elapsedMs\":{:.3},\"writeMsAvg\":{:.3},\"deviceRxMsAvg\":{},\"mbps\":{:.3},\"mibPerSec\":{:.3},\"error\":{}}}",
        ok_frames == frames,
        wait_status,
        bytes,
        frames,
        ok_frames,
        elapsed_ms,
        if ok_frames > 0 { write_ms_total / ok_frames as f64 } else { 0.0 },
        if ok_frames > 0 { format!("{:.3}", rx_ms_total as f64 / ok_frames as f64) } else { "null".to_string() },
        mbps,
        mib_s,
        optional_json_string(last_error.as_deref())
    );
    if ok_frames == frames { Ok(()) } else { Err(()) }
}

fn bench_rx_discard(bytes: usize, frames: usize) -> Result<(), ()> {
    if bytes == 0 || bytes > STDIO_MAX_PAYLOAD || frames == 0 {
        return fail("bench-rx-discard requires bytes 1..524288 and frames > 0");
    }
    let payload = vec![0xA5_u8; bytes];
    let mut usb = UsbTransport::new();
    let started = std::time::Instant::now();
    let mut ok_frames = 0_usize;
    let mut write_ms_total = 0.0_f64;
    let mut rx_ms_total = 0_u64;
    let mut last_error: Option<String> = None;

    for _ in 0..frames {
        let result = usb.send_signalrgb_bench_discard(&payload, true);
        write_ms_total += result.write_ms;
        if result.ok {
            ok_frames += 1;
            rx_ms_total += result.rx_ms.unwrap_or(0) as u64;
        } else {
            last_error = result.error;
            break;
        }
    }

    let elapsed_ms = started.elapsed().as_secs_f64() * 1000.0;
    let total_bytes = ok_frames * bytes;
    let mbps = if elapsed_ms > 0.0 {
        (total_bytes as f64 * 8.0) / (elapsed_ms / 1000.0) / 1_000_000.0
    } else {
        0.0
    };
    let mib_s = if elapsed_ms > 0.0 {
        (total_bytes as f64 / 1_048_576.0) / (elapsed_ms / 1000.0)
    } else {
        0.0
    };
    println!(
        "{{\"ok\":{},\"mode\":\"discard\",\"bytesPerFrame\":{},\"frames\":{},\"okFrames\":{},\"elapsedMs\":{:.3},\"writeMsAvg\":{:.3},\"deviceRxMsAvg\":{},\"mbps\":{:.3},\"mibPerSec\":{:.3},\"error\":{}}}",
        ok_frames == frames,
        bytes,
        frames,
        ok_frames,
        elapsed_ms,
        if ok_frames > 0 { write_ms_total / ok_frames as f64 } else { 0.0 },
        if ok_frames > 0 { format!("{:.3}", rx_ms_total as f64 / ok_frames as f64) } else { "null".to_string() },
        mbps,
        mib_s,
        optional_json_string(last_error.as_deref())
    );
    if ok_frames == frames { Ok(()) } else { Err(()) }
}

fn read_file(path: &str) -> Result<Vec<u8>, ()> {
    fs::read(path).map_err(|error| {
        eprintln!(
            "{{\"ok\":false,\"status\":\"read_failed\",\"error\":\"{}\"}}",
            json_escape(&error.to_string())
        );
    })
}

fn print_help() {
    println!("Open AIO native helper");
    println!("commands:");
    println!("  health");
    println!("  protocol-info");
    println!("  packet-info <jpeg>");
    println!("  send-jpeg <jpeg>");
    println!("  bench-rx [bytes] [frames]");
    println!("  bench-rx-nowait [bytes] [frames]");
    println!("  bench-rx-discard [bytes] [frames]");
    println!("  stdio");
}

fn fail(message: &str) -> Result<(), ()> {
    eprintln!(
        "{{\"ok\":false,\"status\":\"error\",\"error\":\"{}\"}}",
        json_escape(message)
    );
    Err(())
}

fn optional_json_string(value: Option<&str>) -> String {
    match value {
        Some(value) => format!("\"{}\"", json_escape(value)),
        None => "null".to_string(),
    }
}

fn optional_json_u32(value: Option<u32>) -> String {
    value
        .map(|value| value.to_string())
        .unwrap_or_else(|| "null".to_string())
}

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}

fn write_json_line(stdout: &mut impl Write, line: &str) -> Result<(), ()> {
    writeln!(stdout, "{line}").map_err(|_| ())?;
    stdout.flush().map_err(|_| ())
}
