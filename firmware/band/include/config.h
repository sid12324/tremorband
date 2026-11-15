#pragma once

// ESP32-S3-DevKitC-1. Upload and Serial use the CH343 UART bridge (esptool), not USB-CDC.
// UART0 is GPIO43 (TX) and GPIO44 (RX).
// LSM6DS3 I2C is SDA GPIO21 and SCL GPIO22. INT1 is GPIO4.
// Button GPIO2. Battery sense GPIO34.
// Firmware LED GPIO13, active low. Motor pin GPIO25.
// LED, battery, and motor stay off GPIO1, GPIO3, and the I2C pins.
// No vibration motor.

// One sample-rate constant for the firmware. ml/features.py uses the same 104.0.
constexpr float TB_FS_HZ = 104.0f;

constexpr int TB_WINDOW_N = 256;
constexpr int TB_HOP = 128;

constexpr int TB_I2C_SDA_PIN = 21;
constexpr int TB_I2C_SCL_PIN = 22;
constexpr int TB_I2C_HZ = 400000;

constexpr int TB_IMU_INT1_PIN = 4;
constexpr int TB_MOTOR_PIN = 25;
constexpr int TB_BUTTON_PIN = 2;
constexpr int TB_BATTERY_PIN = 34;
constexpr int TB_LED_PIN = 13;

constexpr float TB_HPF_HZ = 2.0f;
constexpr float TB_HPF_HZ_MS = 1.5f;
constexpr float TB_LPF_HZ = 15.0f;

// Rule gate. Still is low motion. A tremor candidate also needs a sharp peak
// in 3–12 Hz. TB_PEAK_TOL_HZ covers the parabolic peak estimate.
constexpr float TB_STILL_ACC_RMS = 0.08f;
constexpr float TB_STILL_GYRO_RMS = 1.0f;
constexpr float TB_TREMOR_SHARPNESS = 0.55f;
constexpr float TB_TREMOR_HZ_MIN = 3.0f;
constexpr float TB_TREMOR_HZ_MAX = 12.0f;
constexpr float TB_PEAK_TOL_HZ = 0.15f;

constexpr int TB_SERIAL_BAUD = 115200;
constexpr const char* TB_FW_VERSION = "0.3.0";

// Default IMU is an LSM6DS3 on I2C, using the Adafruit LSM6DS library's
// LSM6DS3 class. 104 Hz, accel ±4 g, gyro ±500 dps. TB_IMU_MPU6050 builds
// the MPU6050 fallback. This band has no vibration motor.
#define TB_IMU_LSM6DS3 1
#define TB_IMU_MPU6050 2
#ifndef TB_IMU_DRIVER
#define TB_IMU_DRIVER TB_IMU_LSM6DS3
#endif

#define TB_SERVER_URL "http://127.0.0.1:8000"
#define TB_DEVICE_ID "band-01"
