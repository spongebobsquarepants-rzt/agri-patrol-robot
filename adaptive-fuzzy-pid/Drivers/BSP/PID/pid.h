#ifndef __PID_H
#define __PID_H

#include "./SYSTEM/sys/sys.h"

typedef struct 
{
    float kp;
    float ki;
    float kd;

    float out_min;
    float out_max;
}Pidparams_t;

typedef struct 
{
    float target;
    float current;
    float difout;
    float out;

    float error0;
    float error1;
    float error2;

    float kp;
    float ki;
    float kd;

    float out_min;
    float out_max;
}PID_t;

void pid_reset(PID_t *pid);
void pid_set_params(PID_t *pid,const Pidparams_t *params);
void pid_init(PID_t *pid,const Pidparams_t *params);
void pid_set_target(PID_t *pid,float target);
float pid_calculate(PID_t *pid,float current);

#endif


/*
      PID计算流程：
    ->pid_init对基础 kp ki kd参数以及输出和积分项进行限幅
    ->pid_set_target 实现对目标值设定
    ->pid_calculate 实现现实输出给电机
*/
