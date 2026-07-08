#include "./BSP/TIMER/btim.h"
#include "./BSP/ENCODER/encoder.h"
#include "./BSP/MOTOR/motor.h"
#include "./BSP/PID/pid.h"
#include "./BSP/PID/fuzzy_pid.h"
#include "main.h"

TIM_HandleTypeDef g_timx_handle;

void btim_tim6_int_init(uint16_t psc,uint16_t arr)
{
    g_timx_handle.Instance = TIM6;
    g_timx_handle.Init.Prescaler = psc;
    g_timx_handle.Init.Period = arr;
    g_timx_handle.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;

    HAL_TIM_Base_Init(&g_timx_handle);

    HAL_TIM_Base_Start_IT(&g_timx_handle);
}

void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *htim)
{
    if(htim->Instance == TIM6)
    {
        __HAL_RCC_TIM6_CLK_ENABLE();
        HAL_NVIC_SetPriority(TIM6_DAC_IRQn,2,1);
        HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn);
    }
}

void TIM6_DAC_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&g_timx_handle);
}

float current_motor1 = 0.0f;
float current_motor2 = 0.0f;
int32_t flag = 0;
float current_temp = 0.0f;
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if(htim->Instance == TIM6)
    {
        flag++;
        //pid_calculate(&pid_motor1);   
        //motor1_set_speed((int16_t)pid_motor1.out);

        current_motor1 = motor1_encoder_speed_update();
        motor1_set_speed((int16_t)fuzzy_pid_calculate_output(&fuzzy_motor1,&pid_motor1,&pid_params_motor,current_motor1));
        //motor2_set_speed((int16_t)fuzzy_pid_calculate_output(&fuzzy_motor2,&pid_motor2,&pid_params_motor,current_motor2));
    }
}
