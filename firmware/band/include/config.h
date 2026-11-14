#pragma once

// Pins checked against the Seeed XIAO ESP32-S3 pin map:
// D0 GPIO1, D1 GPIO2, D2 GPIO3, D3 GPIO4, D4 GPIO5 (SDA), D5 GPIO6 (SCL),
// user LED GPIO21 active low. GPIO3 is a strapping pin; leave it as an input.

// One sample-rate constant for the firmware. ml/features.py uses the same 104.0.
constexpr float TB_FS_HZ = 104.0f;

constexpr int TB_WINDOW_N = 256;
constexpr int TB_HOP = 128;

constexpr int TB_I2C_SDA_PIN = 5;
constexpr int TB_I2C_SCL_PIN = 6;
constexpr int TB_I2C_HZ = 400000;

constexpr int TB_IMU_INT1_PIN = 4;
constexpr int TB_MOTOR_PIN = 1;
constexpr int TB_BUTTON_PIN = 2;
constexpr int TB_BATTERY_PIN = 3;
constexpr int TB_LED_PIN = 21;

constexpr float TB_HPF_HZ = 2.0f;
constexpr float TB_HPF_HZ_MS = 1.5f;
constexpr float TB_LPF_HZ = 15.0f;

constexpr int TB_SERIAL_BAUD = 115200;

#define TB_IMU_LSM6DSOX 1
#define TB_IMU_MPU6050 2
#ifndef TB_IMU_DRIVER
#define TB_IMU_DRIVER TB_IMU_LSM6DSOX
#endif

#define TB_SERVER_URL "http://127.0.0.1:8000"
#define TB_DEVICE_ID "band-01"
