#ifndef __ENCODER_H
#define __ENCODER_H

#include "./SYSTEM/sys/sys.h"

#define GEAR_RATIO          9.6f      // 减速比 1:9.6
#define ENCODER_PPR         11.0f     // 编码器线数
#define ENCODER_X4          4.0f      // 四倍频
#define SAMPLE_TIME_S       0.1f    // 100ms

typedef struct 
{
    uint16_t encoder_last;
    int16_t encoder_diff;
    float motor_rps;
    float motor_rpm;
}encoder_speed;

extern encoder_speed encoder1_speed;
extern encoder_speed encoder2_speed;

void encoder1_tim3_init(void);
void encoder2_tim4_init(void);
int16_t motor1_encoder_speed_update(void);
void motor2_encoder_speed_update(void);

#endif

