#ifndef __FUZZY_PID_H
#define __FUZZY_PID_H

#include "./SYSTEM/sys/sys.h"
#include "./BSP/PID/pid.h"

#define FUZZY_SET_SIZE  7

#define PB 3.0f     // 正大
#define PM 2.0f     // 正中
#define PS 1.0f     // 正小
#define ZO 0.0f     // 零
#define NS -1.0f    // 负小
#define NM -2.0f    // 负中
#define NB -3.0f    // 负大


typedef struct 
{
    float Ke;       // 误差e的输入缩放  (把实际误差 e 映射到模糊论域)
    float ke_last;
    float Kec;      // 误差变化率ec的输入缩放

    float Kp_out;   // dkp 的输出缩放   (把模糊推理结果映射回真实PID参数增量)
    float Ki_out;   // dki 的输出缩放
    float Kd_out;   // dkd 的输出缩放

    const float *rule_table_kp;     // 规则表
    const float *rule_table_ki;
    const float *rule_table_kd;
}FuzzyPID_t;

void fuzzy_pid_init(FuzzyPID_t *fuzzy,
                    float ke,float kec,
                    float kp_out,float ki_out,float kd_out);

void fuzzy_pid_calculate(FuzzyPID_t *fuzzy,
                         float e,float ec,
                         float *delta_kp,
                         float *delta_ki,
                         float *delta_kd);

float fuzzy_pid_calculate_output(FuzzyPID_t *fuzzy,PID_t *pid,const Pidparams_t *base_params,float current);


#endif


/*      模糊PID简述
    ->实际作用还是依靠原始PID，但与原始PID比例系数固定不同，模糊PID可以根据当前误差和误差变化率
    修改比例系数，实现比例系数实时调节
    ->人为设定误差和误差变化率最大值和最小值，并将其映射至模糊域内，将通过传感器获取到的误差和误
    差变化率映射到模糊域内，判断隶属于哪两个规则，通过对应规则获取增量，将增量加于原始比例系数，
    并对应作用于电机实现调节
*/
