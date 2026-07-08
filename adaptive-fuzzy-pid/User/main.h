#ifndef __MAIN_H
#define __MAIN_H

#include "./SYSTEM/sys/sys.h"
#include "./BSP/PID/pid.h"
#include "./BSP/PID/fuzzy_pid.h"

#define MOTOR_TARGET_RPM      300.0f / 60.0f / 10.0f * 9.6f * 44.0f
#define FUZZY_E_MAX_RPM       240.0f
#define FUZZY_EC_MAX_RPM      75.0f
#define FUZZY_KP_OUT_GAIN     0.6f
#define FUZZY_KI_OUT_GAIN     0.002f
#define FUZZY_KD_OUT_GAIN     0.05f

extern PID_t pid_motor1;
extern PID_t pid_motor2;

extern FuzzyPID_t fuzzy_motor1;
extern FuzzyPID_t fuzzy_motor2;

extern const Pidparams_t pid_params_motor;

#endif
