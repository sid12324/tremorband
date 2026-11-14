#include "imu.h"

#include "config.h"

#include <Adafruit_MPU6050.h>
#include <Wire.h>

namespace {

constexpr float kRadToDeg = 57.2957795f;

class Mpu6050Driver : public ImuDriver {
 public:
  bool begin() override {
    Wire.begin(TB_I2C_SDA_PIN, TB_I2C_SCL_PIN, TB_I2C_HZ);
    if (!device_.begin()) {
      return false;
    }
    device_.setAccelerometerRange(MPU6050_RANGE_4_G);
    device_.setGyroRange(MPU6050_RANGE_500_DEG);
    device_.setFilterBandwidth(MPU6050_BAND_44_HZ);
    // DLPF on keeps the MPU6050 base rate at 1 kHz. Divisor 9 is 100 Hz,
    // the closest step to TB_FS_HZ. The analysis clock stays 104.0 Hz.
    device_.setSampleRateDivisor(9);
    return true;
  }

  bool read(ImuSample& sample) override {
    sensors_event_t accel;
    sensors_event_t gyro;
    sensors_event_t temp;
    if (!device_.getEvent(&accel, &gyro, &temp)) {
      return false;
    }
    sample.ax = accel.acceleration.x;
    sample.ay = accel.acceleration.y;
    sample.az = accel.acceleration.z;
    sample.gx = gyro.gyro.x * kRadToDeg;
    sample.gy = gyro.gyro.y * kRadToDeg;
    sample.gz = gyro.gyro.z * kRadToDeg;
    return true;
  }

  const char* name() const override { return "mpu6050"; }

 private:
  Adafruit_MPU6050 device_;
};

}  // namespace

ImuDriver* make_mpu6050() { return new Mpu6050Driver(); }
