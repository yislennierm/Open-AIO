# Hardware

## Display

The firmware targets the LilyGO T-RGB 2.1-inch half-circle board:

- MCU: ESP32-S3R8
- Flash: 16MB
- PSRAM: 8MB OPI
- LCD: 480x480 ST7701S RGB panel
- Touch: FT3267

The board uses a 3-wire SPI initialization path plus an RGB565 parallel display path. It is not a generic SPI round TFT.

## T-RGB Pin Map

Control:

- Backlight: GPIO46
- HSYNC: GPIO47
- VSYNC: GPIO41
- DE: GPIO45
- PCLK: GPIO42
- I2C SDA: GPIO8
- I2C SCL: GPIO48
- Touch IRQ/RST: GPIO1
- Battery ADC: GPIO4

RGB data:

- B0..B5: GPIO44, GPIO21, GPIO18, GPIO17, GPIO16, GPIO15
- G0..G5: GPIO14, GPIO13, GPIO12, GPIO11, GPIO10, GPIO9
- R0..R5: GPIO43, GPIO7, GPIO6, GPIO5, GPIO3, GPIO2

Panel init over the board I/O expander:

- RST: IO expander IO6
- CS: IO expander IO3
- MOSI: IO expander IO4
- SCLK: IO expander IO5

## Power

Use USB 5V power from a motherboard USB header, rear USB port, or another proper USB 5V supply. Do not power the ESP32/display from a fan header or pump header.

## Mounting

Mount the screen on a decorative top surface, bracket, magnets, or thin adhesive. Do not mount it directly on a hot metal contact surface.

Keep the water block serviceable. The display and cable should be removable without draining the loop or blocking block screws.

## Cable Routing

Route cables away from fans, pump impellers, sharp heatsink fins, and hot VRM heatsinks. Leave enough slack for case side panel removal and water block maintenance.
