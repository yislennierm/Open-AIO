use napi::bindgen_prelude::*;
use napi_derive::napi;
use rusb::{DeviceHandle, GlobalContext};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub const VID: u16 = 0x303A;
pub const PID: u16 = 0x4004;
pub const OUT_ENDPOINT: u8 = 0x01;
pub const IN_ENDPOINT: u8 = 0x81;
pub const CHUNK_SIZE: usize = 64 * 1024;
pub const TIMEOUT_MS: u64 = 250;

pub const SIGNALRGB_MAGIC: &[u8; 4] = b"SRGB";
pub const CMD_SIGNALRGB_RGB565_RECT: u8 = 0x01;
pub const CMD_SIGNALRGB_FLUSH: u8 = 0x02;
pub const CMD_SIGNALRGB_JPEG: u8 = 0x05;
pub const CMD_SIGNALRGB_RGB565_FRAME: u8 = 0x06;
pub const CMD_SIGNALRGB_BENCH_RX: u8 = 0x07;
pub const CMD_SIGNALRGB_BENCH_DISCARD: u8 = 0x08;

#[napi(object)]
pub struct ProtocolInfo {
    pub vid: u32,
    pub pid: u32,
    pub out_endpoint: u32,
    pub in_endpoint: u32,
    pub chunk_size: u32,
    pub jpeg_command: u32,
}

#[napi(object)]
pub struct UsbWriteResult {
    pub ok: bool,
    pub status: String,
    pub error: Option<String>,
    pub bytes: u32,
    pub write_ms: f64,
    pub device_status: Option<u32>,
    pub rx_ms: Option<u32>,
    pub decode_ms: Option<u32>,
    pub flush_ms: Option<u32>,
}

#[napi]
pub fn protocol_info() -> ProtocolInfo {
    ProtocolInfo {
        vid: VID as u32,
        pid: PID as u32,
        out_endpoint: OUT_ENDPOINT as u32,
        in_endpoint: IN_ENDPOINT as u32,
        chunk_size: CHUNK_SIZE as u32,
        jpeg_command: CMD_SIGNALRGB_JPEG as u32,
    }
}

#[napi]
pub fn make_signalrgb_jpeg_header(
    jpeg: Buffer,
    scale: Option<u32>,
    wait_status: Option<bool>,
) -> Result<Buffer> {
    if jpeg.is_empty() {
        return Err(Error::from_reason("empty jpeg frame"));
    }
    let flags = ((scale.unwrap_or(0) as u8) & 0x7f)
        | if wait_status.unwrap_or(false) {
            0x80
        } else {
            0
        };
    Ok(build_signalrgb_jpeg_header(&jpeg, flags).to_vec().into())
}

pub fn signalrgb_jpeg_header(
    jpeg: &[u8],
    scale: u8,
    wait_status: bool,
) -> std::result::Result<Vec<u8>, String> {
    if jpeg.is_empty() {
        return Err("empty jpeg frame".to_string());
    }
    let flags = (scale & 0x7f) | if wait_status { 0x80 } else { 0 };
    Ok(build_signalrgb_jpeg_header(jpeg, flags).to_vec())
}

#[napi]
pub struct OpenAioUsb {
    inner: Mutex<UsbTransport>,
}

#[napi]
impl OpenAioUsb {
    #[napi(constructor)]
    pub fn new() -> Self {
        Self {
            inner: Mutex::new(UsbTransport::new()),
        }
    }

    #[napi]
    pub fn send_signalrgb_jpeg(&self, jpeg: Buffer, scale: Option<u32>) -> Result<UsbWriteResult> {
        if jpeg.is_empty() {
            return Ok(UsbWriteResult {
                ok: false,
                status: "payload_rejected".to_string(),
                error: Some("empty jpeg frame".to_string()),
                bytes: 0,
                write_ms: 0.0,
                device_status: None,
                rx_ms: None,
                decode_ms: None,
                flush_ms: None,
            });
        }

        let flags = ((scale.unwrap_or(0) as u8) & 0x7f) | 0x00;
        let mut transport = self
            .inner
            .lock()
            .map_err(|_| Error::from_reason("usb transport lock poisoned"))?;
        Ok(transport.send_signalrgb_jpeg(&jpeg, flags))
    }

    #[napi]
    pub fn close(&self) -> Result<()> {
        let mut transport = self
            .inner
            .lock()
            .map_err(|_| Error::from_reason("usb transport lock poisoned"))?;
        transport.close();
        Ok(())
    }
}

pub struct UsbTransport {
    handle: Option<DeviceHandle<GlobalContext>>,
}

impl UsbTransport {
    pub fn new() -> Self {
        Self { handle: None }
    }

    pub fn close(&mut self) {
        if let Some(handle) = self.handle.take() {
            let _ = handle.release_interface(0);
        }
    }

    pub fn send_signalrgb_jpeg(&mut self, jpeg: &[u8], flags: u8) -> UsbWriteResult {
        let header = build_signalrgb_jpeg_header(jpeg, flags);
        self.write(&header, jpeg)
    }

    pub fn send_signalrgb_rgb565_rect(
        &mut self,
        x: u16,
        y: u16,
        width: u16,
        height: u16,
        pixels: &[u8],
        flags: u8,
    ) -> UsbWriteResult {
        let expected_len = width as usize * height as usize * 2;
        if pixels.len() != expected_len {
            return UsbWriteResult {
                ok: false,
                status: "payload_rejected".to_string(),
                error: Some(format!("rgb565 length {} != {}", pixels.len(), expected_len)),
                bytes: pixels.len() as u32,
                write_ms: 0.0,
                device_status: None,
                rx_ms: None,
                decode_ms: None,
                flush_ms: None,
            };
        }
        let header = build_signalrgb_rect_header(x, y, width, height, pixels, flags);
        self.write(&header, pixels)
    }

    pub fn flush_signalrgb_frame(&mut self, wait_status: bool) -> UsbWriteResult {
        let header = build_signalrgb_flush_header(wait_status);
        self.write(&header, &[])
    }

    pub fn send_signalrgb_rgb565_frame(&mut self, pixels: &[u8], flags: u8) -> UsbWriteResult {
        let header = build_signalrgb_frame_header(pixels, flags);
        self.write(&header, pixels)
    }

    pub fn send_signalrgb_bench_rx(&mut self, payload: &[u8], wait_status: bool) -> UsbWriteResult {
        let header = build_signalrgb_bench_header(payload, wait_status);
        self.write(&header, payload)
    }

    pub fn send_signalrgb_bench_discard(&mut self, payload: &[u8], wait_status: bool) -> UsbWriteResult {
        let header = build_signalrgb_discard_header(payload, wait_status);
        self.write(&header, payload)
    }

    fn connect(&mut self) -> Result<&mut DeviceHandle<GlobalContext>> {
        if self.handle.is_none() {
            let handle = rusb::open_device_with_vid_pid(VID, PID)
                .ok_or_else(|| Error::from_reason("Open AIO USB device not found"))?;
            let _ = handle.set_active_configuration(1);
            let _ = handle.claim_interface(0);
            self.handle = Some(handle);
        }
        self.handle
            .as_mut()
            .ok_or_else(|| Error::from_reason("Open AIO USB device unavailable"))
    }

    fn write(&mut self, header: &[u8], payload: &[u8]) -> UsbWriteResult {
        let started = Instant::now();
        match self.write_inner(header, payload) {
            Ok(device_status) => UsbWriteResult {
                ok: true,
                status: "ok".to_string(),
                error: None,
                bytes: payload.len() as u32,
                write_ms: elapsed_ms(started),
                device_status: device_status.as_ref().map(|status| status.status as u32),
                rx_ms: device_status.as_ref().map(|status| status.rx_ms as u32),
                decode_ms: device_status.as_ref().map(|status| status.decode_ms as u32),
                flush_ms: device_status.as_ref().map(|status| status.flush_ms as u32),
            },
            Err(error) => {
                self.close();
                UsbWriteResult {
                    ok: false,
                    status: "write_failed".to_string(),
                    error: Some(error.to_string()),
                    bytes: payload.len() as u32,
                    write_ms: elapsed_ms(started),
                    device_status: None,
                    rx_ms: None,
                    decode_ms: None,
                    flush_ms: None,
                }
            }
        }
    }

    fn write_inner(&mut self, header: &[u8], payload: &[u8]) -> Result<Option<DeviceStatus>> {
        let timeout = Duration::from_millis(TIMEOUT_MS);
        let wait_status = header.get(5).copied().unwrap_or(0) & 0x80 != 0;
        let handle = self.connect()?;
        if wait_status {
            drain_status(handle);
        }
        handle
            .write_bulk(OUT_ENDPOINT, header, timeout)
            .map_err(|error| Error::from_reason(format!("USB header write failed: {error}")))?;
        for chunk in payload.chunks(CHUNK_SIZE) {
            handle
                .write_bulk(OUT_ENDPOINT, chunk, timeout)
                .map_err(|error| {
                    Error::from_reason(format!("USB payload write failed: {error}"))
                })?;
        }
        if wait_status {
            return Ok(read_status(handle));
        }
        Ok(None)
    }
}

struct DeviceStatus {
    status: u8,
    rx_ms: u16,
    decode_ms: u16,
    flush_ms: u16,
}

fn drain_status(handle: &mut DeviceHandle<GlobalContext>) {
    let timeout = Duration::from_millis(1);
    let mut buffer = [0_u8; 64];
    for _ in 0..16 {
        if handle.read_bulk(IN_ENDPOINT, &mut buffer, timeout).is_err() {
            break;
        }
    }
}

fn read_status(handle: &mut DeviceHandle<GlobalContext>) -> Option<DeviceStatus> {
    let deadline = Instant::now() + Duration::from_millis(1000);
    let mut buffer = [0_u8; 64];
    while Instant::now() < deadline {
        match handle.read_bulk(IN_ENDPOINT, &mut buffer, Duration::from_millis(10)) {
            Ok(len) if len >= 18 && &buffer[0..4] == b"SRSP" => {
                return Some(DeviceStatus {
                    status: buffer[4],
                    rx_ms: u16::from_le_bytes([buffer[12], buffer[13]]),
                    decode_ms: u16::from_le_bytes([buffer[14], buffer[15]]),
                    flush_ms: u16::from_le_bytes([buffer[16], buffer[17]]),
                });
            }
            Ok(_) => {}
            Err(rusb::Error::Timeout) => {}
            Err(_) => return None,
        }
    }
    None
}

fn build_signalrgb_jpeg_header(jpeg: &[u8], flags: u8) -> [u8; 20] {
    let mut header = [0_u8; 20];
    header[0..4].copy_from_slice(SIGNALRGB_MAGIC);
    header[4] = CMD_SIGNALRGB_JPEG;
    header[5] = flags;
    header[6..8].copy_from_slice(&checksum16(jpeg).to_le_bytes());
    header[16..20].copy_from_slice(&(jpeg.len() as u32).to_le_bytes());
    header
}

fn build_signalrgb_rect_header(
    x: u16,
    y: u16,
    width: u16,
    height: u16,
    pixels: &[u8],
    flags: u8,
) -> [u8; 20] {
    let mut header = [0_u8; 20];
    header[0..4].copy_from_slice(SIGNALRGB_MAGIC);
    header[4] = CMD_SIGNALRGB_RGB565_RECT;
    header[5] = flags;
    header[6..8].copy_from_slice(&checksum16(pixels).to_le_bytes());
    header[8..10].copy_from_slice(&x.to_le_bytes());
    header[10..12].copy_from_slice(&y.to_le_bytes());
    header[12..14].copy_from_slice(&width.to_le_bytes());
    header[14..16].copy_from_slice(&height.to_le_bytes());
    header[16..20].copy_from_slice(&(pixels.len() as u32).to_le_bytes());
    header
}

fn build_signalrgb_flush_header(wait_status: bool) -> [u8; 20] {
    let mut header = [0_u8; 20];
    header[0..4].copy_from_slice(SIGNALRGB_MAGIC);
    header[4] = CMD_SIGNALRGB_FLUSH;
    header[5] = if wait_status { 0x80 } else { 0x00 };
    header
}

fn build_signalrgb_frame_header(pixels: &[u8], flags: u8) -> [u8; 20] {
    let mut header = [0_u8; 20];
    header[0..4].copy_from_slice(SIGNALRGB_MAGIC);
    header[4] = CMD_SIGNALRGB_RGB565_FRAME;
    header[5] = flags;
    header[6..8].copy_from_slice(&checksum16(pixels).to_le_bytes());
    header[16..20].copy_from_slice(&(pixels.len() as u32).to_le_bytes());
    header
}

fn build_signalrgb_bench_header(payload: &[u8], wait_status: bool) -> [u8; 20] {
    let mut header = [0_u8; 20];
    header[0..4].copy_from_slice(SIGNALRGB_MAGIC);
    header[4] = CMD_SIGNALRGB_BENCH_RX;
    header[5] = if wait_status { 0x80 } else { 0x00 };
    header[6..8].copy_from_slice(&checksum16(payload).to_le_bytes());
    header[16..20].copy_from_slice(&(payload.len() as u32).to_le_bytes());
    header
}

fn build_signalrgb_discard_header(payload: &[u8], wait_status: bool) -> [u8; 20] {
    let mut header = [0_u8; 20];
    header[0..4].copy_from_slice(SIGNALRGB_MAGIC);
    header[4] = CMD_SIGNALRGB_BENCH_DISCARD;
    header[5] = if wait_status { 0x80 } else { 0x00 };
    header[16..20].copy_from_slice(&(payload.len() as u32).to_le_bytes());
    header
}

fn checksum16(data: &[u8]) -> u16 {
    data.iter()
        .fold(0_u16, |sum, byte| sum.wrapping_add(*byte as u16))
}

fn elapsed_ms(started: Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1000.0
}
