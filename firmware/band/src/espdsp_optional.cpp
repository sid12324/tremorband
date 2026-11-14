// Optional ESP-DSP entry points. The parity-tested pipeline is signal.cpp,
// which uses the esp-dsp 1.8.2 biquad and Hann formulas in double precision.
// Build with -DTB_USE_ESP_DSP=1 only when esp_dsp.h is on the include path.

#include "config.h"

#if defined(TB_USE_ESP_DSP)
#include "esp_dsp.h"

extern "C" void tb_espdsp_link_check() {
  float coeffs[5];
  dsps_biquad_gen_lpf_f32(coeffs, TB_LPF_HZ / TB_FS_HZ, 0.70710678118f);
  dsps_biquad_gen_hpf_f32(coeffs, TB_HPF_HZ / TB_FS_HZ, 0.70710678118f);
  float window[8];
  dsps_wind_hann_f32(window, 8);
  float data[16] = {};
  dsps_fft2r_init_fc32(nullptr, 8);
  dsps_fft2r_fc32(data, 8);
}
#endif
