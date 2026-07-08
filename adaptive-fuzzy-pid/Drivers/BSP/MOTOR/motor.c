#include "./BSP/MOTOR/motor.h"

TIM_HandleTypeDef g_tim9_pwm_handle;
TIM_HandleTypeDef g_tim12_pwm_handle;

void motor1_tim9_pwm_init(uint16_t psc,uint16_t arr)
{
    TIM_OC_InitTypeDef tim9_pwm_chy_oc = {0};

    g_tim9_pwm_handle.Instance = TIM9;
    g_tim9_pwm_handle.Init.Prescaler = psc;
    g_tim9_pwm_handle.Init.CounterMode = TIM_COUNTERMODE_UP;
    g_tim9_pwm_handle.Init.Period = arr;
    g_tim9_pwm_handle.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    g_tim9_pwm_handle.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

    HAL_TIM_PWM_Init(&g_tim9_pwm_handle);

    tim9_pwm_chy_oc.OCMode = TIM_OCMODE_PWM1;
    tim9_pwm_chy_oc.Pulse = 0;
    tim9_pwm_chy_oc.OCPolarity = TIM_OCPOLARITY_HIGH;
    tim9_pwm_chy_oc.OCFastMode = TIM_OCFAST_DISABLE;

    HAL_TIM_PWM_ConfigChannel(&g_tim9_pwm_handle,&tim9_pwm_chy_oc,TIM_CHANNEL_1);
    HAL_TIM_PWM_ConfigChannel(&g_tim9_pwm_handle,&tim9_pwm_chy_oc,TIM_CHANNEL_2);

    HAL_TIM_PWM_Start(&g_tim9_pwm_handle,TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&g_tim9_pwm_handle,TIM_CHANNEL_2);
}

void motor2_tim12_pwm_init(uint16_t psc,uint16_t arr)
{
    TIM_OC_InitTypeDef tim12_pwm_chy_oc = {0};

    g_tim12_pwm_handle.Instance = TIM12;
    g_tim12_pwm_handle.Init.Prescaler = psc;
    g_tim12_pwm_handle.Init.CounterMode = TIM_COUNTERMODE_UP;
    g_tim12_pwm_handle.Init.Period = arr;
    g_tim12_pwm_handle.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    g_tim12_pwm_handle.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

    HAL_TIM_PWM_Init(&g_tim12_pwm_handle);

    tim12_pwm_chy_oc.OCMode = TIM_OCMODE_PWM1;
    tim12_pwm_chy_oc.Pulse = 0;
    tim12_pwm_chy_oc.OCPolarity = TIM_OCPOLARITY_HIGH;
    tim12_pwm_chy_oc.OCFastMode = TIM_OCFAST_DISABLE;

    HAL_TIM_PWM_ConfigChannel(&g_tim12_pwm_handle,&tim12_pwm_chy_oc,TIM_CHANNEL_1);
    HAL_TIM_PWM_ConfigChannel(&g_tim12_pwm_handle,&tim12_pwm_chy_oc,TIM_CHANNEL_2);

    HAL_TIM_PWM_Start(&g_tim12_pwm_handle,TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&g_tim12_pwm_handle,TIM_CHANNEL_2);
}

void HAL_TIM_PWM_MspInit(TIM_HandleTypeDef *htim)
{
    GPIO_InitTypeDef gpio_init_struct = {0};
    if(htim->Instance == TIM9)
    {
        __HAL_RCC_GPIOE_CLK_ENABLE();
        __HAL_RCC_TIM9_CLK_ENABLE();

        gpio_init_struct.Pin = GPIO_PIN_5 | GPIO_PIN_6;
        gpio_init_struct.Mode = GPIO_MODE_AF_PP;
        gpio_init_struct.Pull = GPIO_NOPULL;
        gpio_init_struct.Speed = GPIO_SPEED_FREQ_HIGH;
        gpio_init_struct.Alternate = GPIO_AF3_TIM9;

        HAL_GPIO_Init(GPIOE,&gpio_init_struct);
    }
    
    if(htim->Instance == TIM12)
    {
        __HAL_RCC_GPIOB_CLK_ENABLE();
        __HAL_RCC_TIM12_CLK_ENABLE();

        gpio_init_struct.Pin = GPIO_PIN_14 | GPIO_PIN_15;
        gpio_init_struct.Mode = GPIO_MODE_AF_PP;
        gpio_init_struct.Pull = GPIO_NOPULL;
        gpio_init_struct.Speed = GPIO_SPEED_FREQ_HIGH;
        gpio_init_struct.Alternate = GPIO_AF9_TIM12;
        
        HAL_GPIO_Init(GPIOB,&gpio_init_struct);
    }
}


void motor1_set_speed(int16_t pwm)
{
    uint16_t pwm_abs;
    uint32_t arr;

    arr = __HAL_TIM_GET_AUTORELOAD(&g_tim9_pwm_handle);

    if(pwm >= 0)
    {
        pwm_abs = (uint16_t)pwm;
        if(pwm_abs > arr) pwm_abs = arr;

        __HAL_TIM_SET_COMPARE(&g_tim9_pwm_handle,TIM_CHANNEL_1,pwm_abs);
        __HAL_TIM_SET_COMPARE(&g_tim9_pwm_handle,TIM_CHANNEL_2,0);          //快衰减
    }
    else
    {
        pwm_abs = (uint16_t)(-pwm);
        if(pwm_abs > arr) pwm_abs = arr;

        __HAL_TIM_SET_COMPARE(&g_tim9_pwm_handle,TIM_CHANNEL_1,0);          //快衰减
        __HAL_TIM_SET_COMPARE(&g_tim9_pwm_handle,TIM_CHANNEL_2,pwm_abs);
    }
}

void motor2_set_speed(int16_t pwm)
{
    uint16_t pwm_abs;
    uint32_t arr;

    arr = __HAL_TIM_GET_AUTORELOAD(&g_tim12_pwm_handle);

    if(pwm >= 0)
    {
        pwm_abs = (uint16_t)pwm;
        if(pwm_abs > arr) pwm_abs = arr;

        __HAL_TIM_SET_COMPARE(&g_tim12_pwm_handle,TIM_CHANNEL_1,pwm_abs);
        __HAL_TIM_SET_COMPARE(&g_tim12_pwm_handle,TIM_CHANNEL_2,0);
    }
    else
    {
        pwm_abs = (uint16_t)(-pwm);
        if(pwm_abs > arr) pwm_abs = arr;
        
        __HAL_TIM_SET_COMPARE(&g_tim12_pwm_handle,TIM_CHANNEL_1,0);
        __HAL_TIM_SET_COMPARE(&g_tim12_pwm_handle,TIM_CHANNEL_2,pwm_abs);
    }
}
