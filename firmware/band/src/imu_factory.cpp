#include "imu.h"

#include "config.h"

ImuDriver* make_lsm6dsox();
ImuDriver* make_mpu6050();

ImuDriver* make_imu() {
#if TB_IMU_DRIVER == TB_IMU_MPU6050
  return make_mpu6050();
#else
  return make_lsm6dsox();
#endif
}
