#pragma once

#include <stdint.h>

// One IMU reading. Accel is m/s^2. Gyro is deg/s. t_us is filled by the sampler.
struct ImuSample {
  int64_t t_us;
  float ax;
  float ay;
  float az;
  float gx;
  float gy;
  float gz;
};

class ImuDriver {
 public:
  virtual ~ImuDriver() = default;
  virtual bool begin() = 0;
  virtual bool read(ImuSample& sample) = 0;
  virtual const char* name() const = 0;
};

ImuDriver* make_imu();
