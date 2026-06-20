use open_aio_core::{
    signalrgb_jpeg_header, UsbTransport, CHUNK_SIZE, CMD_SIGNALRGB_JPEG, IN_ENDPOINT, OUT_ENDPOINT,
    PID, VID,
};
use std::env;
use std::fs;
use std::process;

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
                "{{\"vid\":{},\"pid\":{},\"outEndpoint\":{},\"inEndpoint\":{},\"chunkSize\":{},\"jpegCommand\":{}}}",
                VID, PID, OUT_ENDPOINT, IN_ENDPOINT, CHUNK_SIZE, CMD_SIGNALRGB_JPEG
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

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}
