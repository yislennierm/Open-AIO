#include <stdint.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hal/lcd_types.h"

#define LCD_W 480
#define LCD_H 480
#define RGB_MAX_PIXEL_CLOCK_HZ 8000000UL

#define BOARD_TFT_BL GPIO_NUM_46
#define BOARD_TFT_HSYNC GPIO_NUM_47
#define BOARD_TFT_VSYNC GPIO_NUM_41
#define BOARD_TFT_DE GPIO_NUM_45
#define BOARD_TFT_PCLK GPIO_NUM_42

#define BOARD_TFT_DATA1 GPIO_NUM_21
#define BOARD_TFT_DATA2 GPIO_NUM_18
#define BOARD_TFT_DATA3 GPIO_NUM_17
#define BOARD_TFT_DATA4 GPIO_NUM_16
#define BOARD_TFT_DATA5 GPIO_NUM_15
#define BOARD_TFT_DATA6 GPIO_NUM_14
#define BOARD_TFT_DATA7 GPIO_NUM_13
#define BOARD_TFT_DATA8 GPIO_NUM_12
#define BOARD_TFT_DATA9 GPIO_NUM_11
#define BOARD_TFT_DATA10 GPIO_NUM_10
#define BOARD_TFT_DATA11 GPIO_NUM_9
#define BOARD_TFT_DATA13 GPIO_NUM_7
#define BOARD_TFT_DATA14 GPIO_NUM_6
#define BOARD_TFT_DATA15 GPIO_NUM_5
#define BOARD_TFT_DATA16 GPIO_NUM_3
#define BOARD_TFT_DATA17 GPIO_NUM_2

#define BOARD_I2C_SDA GPIO_NUM_8
#define BOARD_I2C_SCL GPIO_NUM_48
#define I2C_PORT I2C_NUM_0
#define XL9555_ADDR 0x20
#define XL9555_OUT0 0x02
#define XL9555_CFG0 0x06

#define XL_IO_POWER_EN 2
#define XL_IO_CS 3
#define XL_IO_MOSI 4
#define XL_IO_SCLK 5
#define XL_IO_RESET 6

static const char *TAG = "open-aio-idf-video-lab";

typedef struct {
    uint8_t cmd;
    uint8_t data[16];
    uint8_t databytes;
} lcd_init_cmd_t;

static const lcd_init_cmd_t st7701_2_8_inches[] = {
    {0xFF, {0x77, 0x01, 0x00, 0x00, 0x13}, 0x05},
    {0xEF, {0x08}, 0x01},
    {0xFF, {0x77, 0x01, 0x00, 0x00, 0x10}, 0x05},
    {0xC0, {0x3B, 0x00}, 0x02},
    {0xC1, {0x10, 0x0C}, 0x02},
    {0xC2, {0x07, 0x0A}, 0x02},
    {0xC7, {0x00}, 0x01},
    {0xCC, {0x10}, 0x01},
    {0xCD, {0x08}, 0x01},
    {0xB0, {0x05, 0x12, 0x98, 0x0e, 0x0F, 0x07, 0x07, 0x09, 0x09, 0x23, 0x05, 0x52, 0x0F, 0x67, 0x2C, 0x11}, 0x10},
    {0xB1, {0x0B, 0x11, 0x97, 0x0C, 0x12, 0x06, 0x06, 0x08, 0x08, 0x22, 0x03, 0x51, 0x11, 0x66, 0x2B, 0x0F}, 0x10},
    {0xFF, {0x77, 0x01, 0x00, 0x00, 0x11}, 0x05},
    {0xB0, {0x5d}, 0x01},
    {0xB1, {0x2D}, 0x01},
    {0xB2, {0x81}, 0x01},
    {0xB3, {0x80}, 0x01},
    {0xB5, {0x4E}, 0x01},
    {0xB7, {0x85}, 0x01},
    {0xB8, {0x20}, 0x01},
    {0xC1, {0x78}, 0x01},
    {0xC2, {0x78}, 0x01},
    {0xD0, {0x88}, 0x01},
    {0xE0, {0x00, 0x00, 0x02}, 0x03},
    {0xE1, {0x06, 0x30, 0x08, 0x30, 0x05, 0x30, 0x07, 0x30, 0x00, 0x33, 0x33}, 0x0b},
    {0xE2, {0x11, 0x11, 0x33, 0x33, 0xf4, 0x00, 0x00, 0x00, 0xf4, 0x00, 0x00, 0x00}, 0x0c},
    {0xE3, {0x00, 0x00, 0x11, 0x11}, 0x04},
    {0xE4, {0x44, 0x44}, 0x02},
    {0xE5, {0x0d, 0xf5, 0x30, 0xf0, 0x0f, 0xf7, 0x30, 0xf0, 0x09, 0xf1, 0x30, 0xf0, 0x0b, 0xf3, 0x30, 0xf0}, 0x10},
    {0xE6, {0x00, 0x00, 0x11, 0x11}, 0x04},
    {0xE7, {0x44, 0x44}, 0x02},
    {0xE8, {0x0c, 0xf4, 0x30, 0xf0, 0x0e, 0xf6, 0x30, 0xf0, 0x08, 0xf0, 0x30, 0xf0, 0x0a, 0xf2, 0x30, 0xf0}, 0x10},
    {0xE9, {0x36}, 0x01},
    {0xEB, {0x00, 0x01, 0xe4, 0xe4, 0x44, 0x88, 0x40}, 0x07},
    {0xED, {0xff, 0x10, 0xaf, 0x76, 0x54, 0x2b, 0xcf, 0xff, 0xff, 0xfc, 0xb2, 0x45, 0x67, 0xfa, 0x01, 0xff}, 0x10},
    {0xEF, {0x08, 0x08, 0x08, 0x45, 0x3f, 0x54}, 0x06},
    {0xFF, {0x77, 0x01, 0x00, 0x00, 0x00}, 0x05},
    {0x11, {0x00}, 0x80},
    {0x3A, {0x66}, 0x01},
    {0x36, {0xC8}, 0x01},
    {0x35, {0x00}, 0x01},
    {0x29, {0x00}, 0x80},
    {0, {0}, 0xff},
};

static uint8_t xl_out0 = 0xff;
static uint8_t xl_cfg0 = 0xff;
static esp_lcd_panel_handle_t panel;
static uint16_t *fb;

static esp_err_t i2c_write_reg(uint8_t addr, uint8_t reg, uint8_t value)
{
    uint8_t data[2] = {reg, value};
    return i2c_master_write_to_device(I2C_PORT, addr, data, sizeof(data), pdMS_TO_TICKS(100));
}

static esp_err_t xl9555_set_output(uint8_t pin, bool high)
{
    if (high) {
        xl_out0 |= (uint8_t)(1U << pin);
    } else {
        xl_out0 &= (uint8_t)~(1U << pin);
    }
    return i2c_write_reg(XL9555_ADDR, XL9555_OUT0, xl_out0);
}

static esp_err_t xl9555_set_output_mode(uint8_t pin)
{
    xl_cfg0 &= (uint8_t)~(1U << pin);
    return i2c_write_reg(XL9555_ADDR, XL9555_CFG0, xl_cfg0);
}

static esp_err_t i2c_init_bus(void)
{
    i2c_config_t config = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = BOARD_I2C_SDA,
        .scl_io_num = BOARD_I2C_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 1000000,
        .clk_flags = 0,
    };
    ESP_RETURN_ON_ERROR(i2c_param_config(I2C_PORT, &config), TAG, "i2c config failed");
    return i2c_driver_install(I2C_PORT, I2C_MODE_MASTER, 0, 0, 0);
}

static esp_err_t panel_gpio_init(void)
{
    gpio_config_t bl = {
        .pin_bit_mask = 1ULL << BOARD_TFT_BL,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&bl), TAG, "backlight gpio config failed");
    gpio_set_level(BOARD_TFT_BL, 0);

    ESP_RETURN_ON_ERROR(xl9555_set_output_mode(XL_IO_POWER_EN), TAG, "power cfg failed");
    ESP_RETURN_ON_ERROR(xl9555_set_output_mode(XL_IO_CS), TAG, "cs cfg failed");
    ESP_RETURN_ON_ERROR(xl9555_set_output_mode(XL_IO_MOSI), TAG, "mosi cfg failed");
    ESP_RETURN_ON_ERROR(xl9555_set_output_mode(XL_IO_SCLK), TAG, "sclk cfg failed");
    ESP_RETURN_ON_ERROR(xl9555_set_output_mode(XL_IO_RESET), TAG, "reset cfg failed");

    ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_POWER_EN, true), TAG, "power enable failed");
    ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_CS, true), TAG, "cs high failed");
    ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_SCLK, false), TAG, "sclk low failed");
    ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_MOSI, false), TAG, "mosi low failed");
    return ESP_OK;
}

static esp_err_t transfer9(uint16_t value)
{
    ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_CS, false), TAG, "cs low failed");
    for (int i = 8; i >= 0; --i) {
        ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_SCLK, false), TAG, "sclk low failed");
        ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_MOSI, (value >> i) & 1U), TAG, "mosi failed");
        ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_SCLK, true), TAG, "sclk high failed");
    }
    ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_SCLK, false), TAG, "sclk final low failed");
    return xl9555_set_output(XL_IO_CS, true);
}

static esp_err_t write_command(uint8_t cmd)
{
    return transfer9(cmd);
}

static esp_err_t write_data(const uint8_t *data, int len)
{
    for (int i = 0; i < len; ++i) {
        ESP_RETURN_ON_ERROR(transfer9((uint16_t)data[i] | 0x100U), TAG, "data transfer failed");
    }
    return ESP_OK;
}

static esp_err_t st7701_init(void)
{
    ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_RESET, false), TAG, "reset low failed");
    vTaskDelay(pdMS_TO_TICKS(20));
    ESP_RETURN_ON_ERROR(xl9555_set_output(XL_IO_RESET, true), TAG, "reset high failed");
    vTaskDelay(pdMS_TO_TICKS(10));

    for (int i = 0; st7701_2_8_inches[i].databytes != 0xff; ++i) {
        ESP_RETURN_ON_ERROR(write_command(st7701_2_8_inches[i].cmd), TAG, "cmd failed");
        ESP_RETURN_ON_ERROR(write_data(st7701_2_8_inches[i].data, st7701_2_8_inches[i].databytes & 0x1f), TAG, "data failed");
        if (st7701_2_8_inches[i].databytes & 0x80) {
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }
    return ESP_OK;
}

static esp_err_t rgb_panel_init(void)
{
    const int data_gpio_nums[16] = {
        BOARD_TFT_DATA13,
        BOARD_TFT_DATA14,
        BOARD_TFT_DATA15,
        BOARD_TFT_DATA16,
        BOARD_TFT_DATA17,
        BOARD_TFT_DATA6,
        BOARD_TFT_DATA7,
        BOARD_TFT_DATA8,
        BOARD_TFT_DATA9,
        BOARD_TFT_DATA10,
        BOARD_TFT_DATA11,
        BOARD_TFT_DATA1,
        BOARD_TFT_DATA2,
        BOARD_TFT_DATA3,
        BOARD_TFT_DATA4,
        BOARD_TFT_DATA5,
    };

    esp_lcd_rgb_panel_config_t panel_config = {
        .clk_src = LCD_CLK_SRC_PLL160M,
        .timings = {
            .pclk_hz = RGB_MAX_PIXEL_CLOCK_HZ,
            .h_res = LCD_W,
            .v_res = LCD_H,
            .hsync_pulse_width = 1,
            .hsync_back_porch = 30,
            .hsync_front_porch = 50,
            .vsync_pulse_width = 1,
            .vsync_back_porch = 30,
            .vsync_front_porch = 20,
            .flags = {
                .pclk_active_neg = true,
            },
        },
        .data_width = 16,
        .bits_per_pixel = 16,
        .num_fbs = 1,
        .psram_trans_align = 64,
        .hsync_gpio_num = BOARD_TFT_HSYNC,
        .vsync_gpio_num = BOARD_TFT_VSYNC,
        .de_gpio_num = BOARD_TFT_DE,
        .pclk_gpio_num = BOARD_TFT_PCLK,
        .disp_gpio_num = GPIO_NUM_NC,
        .data_gpio_nums = {
            [0 ... 15] = GPIO_NUM_NC,
        },
        .flags = {
            .fb_in_psram = true,
        },
    };
    memcpy(panel_config.data_gpio_nums, data_gpio_nums, sizeof(data_gpio_nums));

    ESP_RETURN_ON_ERROR(esp_lcd_new_rgb_panel(&panel_config, &panel), TAG, "new rgb panel failed");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(panel), TAG, "rgb panel reset failed");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(panel), TAG, "rgb panel init failed");
    ESP_RETURN_ON_ERROR(esp_lcd_rgb_panel_get_frame_buffer(panel, 1, (void **)&fb), TAG, "get framebuffer failed");
    return ESP_OK;
}

static uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b)
{
    return (uint16_t)(((r & 0xf8) << 8) | ((g & 0xfc) << 3) | (b >> 3));
}

static void draw_pattern(uint32_t frame)
{
    const uint16_t colors[] = {
        rgb565(255, 0, 0), rgb565(0, 255, 0), rgb565(0, 0, 255),
        rgb565(255, 255, 255), rgb565(0, 0, 0), rgb565(255, 255, 0),
    };
    uint32_t shift = frame % LCD_W;
    for (int y = 0; y < LCD_H; ++y) {
        uint16_t *row = fb + (y * LCD_W);
        for (int x = 0; x < LCD_W; ++x) {
            uint32_t band = ((uint32_t)x + shift) / 80U;
            uint16_t c = colors[band % (sizeof(colors) / sizeof(colors[0]))];
            if (((x / 24) ^ (y / 24) ^ (frame / 30)) & 1) {
                c ^= 0x0841;
            }
            row[x] = c;
        }
    }

    int box_x = (int)((frame * 7) % (LCD_W - 96));
    int box_y = (int)((frame * 3) % (LCD_H - 64));
    for (int y = box_y; y < box_y + 64; ++y) {
        uint16_t *row = fb + (y * LCD_W);
        for (int x = box_x; x < box_x + 96; ++x) {
            row[x] = rgb565(255, 80, 220);
        }
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "starting isolated panel-only video lab");
    ESP_ERROR_CHECK(i2c_init_bus());
    ESP_ERROR_CHECK(panel_gpio_init());
    ESP_ERROR_CHECK(st7701_init());
    ESP_ERROR_CHECK(rgb_panel_init());
    gpio_set_level(BOARD_TFT_BL, 1);
    ESP_LOGI(TAG, "panel running: %dx%d pclk=%lu", LCD_W, LCD_H, (unsigned long)RGB_MAX_PIXEL_CLOCK_HZ);

    uint32_t frame = 0;
    int64_t last_log = esp_timer_get_time();
    uint32_t frames_since_log = 0;
    while (true) {
        draw_pattern(frame++);
        frames_since_log++;
        int64_t now = esp_timer_get_time();
        if (now - last_log >= 1000000) {
            ESP_LOGI(TAG, "pattern fps=%lu", (unsigned long)frames_since_log);
            frames_since_log = 0;
            last_log = now;
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}
