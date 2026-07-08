#ifndef __MOTOR_H
#define __MOTOR_H

#include "./SYSTEM/sys/sys.h"

void motor1_tim9_pwm_init(uint16_t psc,uint16_t arr);
void motor2_tim12_pwm_init(uint16_t psc,uint16_t arr);
void motor1_set_speed(int16_t pwm);
void motor2_set_speed(int16_t pwm);


#endif
