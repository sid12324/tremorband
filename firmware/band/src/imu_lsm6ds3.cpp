#include "imu.h"

#include "config.h"

#include <Adafruit_LSM6DS3.h>
#include <Wire.h>

namespace {

constexpr float kRadToDeg = 57.2957795f;

class Lsm6ds3Driver : public ImuDriver {
 public:
  bool begin() override {
    Wire.begin(TB_I2C_SDA_PIN, TB_I2C_SCL_PIN, TB_I2C_HZ);
    if (!device_.begin_I2C()) {
      return false;
    }
    device_.setAccelDataRate(LSM6DS_RATE_104_HZ);
    device_.setGyroDataRate(LSM6DS_RATE_104_HZ);
    device_.setAccelRange(LSM6DS_ACCEL_RANGE_4_G);
    device_.setGyroRange(LSM6DS_GYRO_RANGE_500_DPS);
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

  const char* name() const override { return "lsm6ds3"; }

 private:
  Adafruit_LSM6DS3 device_;
};

}  // namespace

ImuDriver* make_lsm6ds3() { return new Lsm6ds3Driver(); }
