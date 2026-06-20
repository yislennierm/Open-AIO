from pathlib import Path

Import("env")

framework_dir = Path(env.PioPlatform().get_package_dir("framework-arduinoespressif32"))
usb_vendor = framework_dir / "libraries" / "USB" / "src" / "USBVendor.cpp"
sdk_dir = framework_dir / "tools" / "sdk" / "esp32s3"

source = usb_vendor.read_text()

if "FAST_STREAM_BUFFER_PATCH" not in source:
    source = source.replace(
        '#include "esp32-hal-tinyusb.h"\n',
        '#include "esp32-hal-tinyusb.h"\n#include "freertos/stream_buffer.h" // FAST_STREAM_BUFFER_PATCH\n',
    )
    source = source.replace(
        "static xQueueHandle rx_queue = NULL;\n",
        "static StreamBufferHandle_t rx_stream = NULL; // FAST_STREAM_BUFFER_PATCH\n",
    )
    source = source.replace(
        """size_t USBVendor::setRxBufferSize(size_t rx_queue_len){
    if(rx_queue){
        if(!rx_queue_len){
            vQueueDelete(rx_queue);
            rx_queue = NULL;
        }
        return 0;
    }
    rx_queue = xQueueCreate(rx_queue_len, sizeof(uint8_t));
    if(!rx_queue){
        return 0;
    }
    return rx_queue_len;
}
""",
        """size_t USBVendor::setRxBufferSize(size_t rx_queue_len){
    if(rx_stream){
        if(!rx_queue_len){
            vStreamBufferDelete(rx_stream);
            rx_stream = NULL;
        }
        return 0;
    }
    rx_stream = xStreamBufferCreate(rx_queue_len, 1);
    if(!rx_stream){
        return 0;
    }
    return rx_queue_len;
}
""",
    )
    source = source.replace(
        """void USBVendor::_onRX(const uint8_t* buffer, size_t len){
    for(uint32_t i=0; i<len; i++){
        if(rx_queue == NULL || !xQueueSend(rx_queue, buffer+i, 0)){
            len = i+1;
            log_e("RX Queue Overflow");
            break;
        }
    }
    arduino_usb_vendor_event_data_t p;
    p.data.len = len;
    arduino_usb_event_post(ARDUINO_USB_VENDOR_EVENTS, ARDUINO_USB_VENDOR_DATA_EVENT, &p, sizeof(arduino_usb_vendor_event_data_t), portMAX_DELAY);
}
""",
        """void USBVendor::_onRX(const uint8_t* buffer, size_t len){
    if(rx_stream == NULL || buffer == NULL || len == 0){
        len = 0;
    } else {
        size_t written = xStreamBufferSend(rx_stream, buffer, len, 0);
        if(written != len){
            len = written;
            log_e("RX Stream Overflow");
        }
    }
    arduino_usb_vendor_event_data_t p;
    p.data.len = len;
    arduino_usb_event_post(ARDUINO_USB_VENDOR_EVENTS, ARDUINO_USB_VENDOR_DATA_EVENT, &p, sizeof(arduino_usb_vendor_event_data_t), portMAX_DELAY);
}
""",
    )
    source = source.replace(
        """int USBVendor::available(void){
    if(rx_queue == NULL){
        return -1;
    }
    return uxQueueMessagesWaiting(rx_queue);
}
""",
        """int USBVendor::available(void){
    if(rx_stream == NULL){
        return -1;
    }
    return xStreamBufferBytesAvailable(rx_stream);
}
""",
    )
    source = source.replace(
        """int USBVendor::peek(void){
    if(rx_queue == NULL){
        return -1;
    }
    uint8_t c;
    if(xQueuePeek(rx_queue, &c, 0)) {
        return c;
    }
    return -1;
}
""",
        """int USBVendor::peek(void){
    return -1;
}
""",
    )
    source = source.replace(
        """int USBVendor::read(void){
    if(rx_queue == NULL){
        return -1;
    }
    uint8_t c = 0;
    if(xQueueReceive(rx_queue, &c, 0)) {
        return c;
    }
    return -1;
}
""",
        """int USBVendor::read(void){
    if(rx_stream == NULL){
        return -1;
    }
    uint8_t c = 0;
    if(xStreamBufferReceive(rx_stream, &c, 1, 0) == 1) {
        return c;
    }
    return -1;
}
""",
    )
    source = source.replace(
        """size_t USBVendor::read(uint8_t *buffer, size_t size){
    if(rx_queue == NULL){
        return -1;
    }
    uint8_t c = 0;
    size_t count = 0;
    while(count < size && xQueueReceive(rx_queue, &c, 0)){
        buffer[count++] = c;
    }
    return count;
}
""",
        """size_t USBVendor::read(uint8_t *buffer, size_t size){
    if(rx_stream == NULL){
        return -1;
    }
    return xStreamBufferReceive(rx_stream, buffer, size, 0);
}
""",
    )
    usb_vendor.write_text(source)
    print("Patched Arduino USBVendor to use stream buffer bulk RX")

for sdkconfig in sdk_dir.glob("*/include/sdkconfig.h"):
    text = sdkconfig.read_text()
    text = text.replace("#define CONFIG_TINYUSB_VENDOR_RX_BUFSIZE 64", "#define CONFIG_TINYUSB_VENDOR_RX_BUFSIZE 4096")
    text = text.replace("#define CONFIG_TINYUSB_VENDOR_TX_BUFSIZE 64", "#define CONFIG_TINYUSB_VENDOR_TX_BUFSIZE 512")
    sdkconfig.write_text(text)

