#include "./BSP/ENCODER/encoder.h"

TIM_HandleTypeDef g_tim3_encoder1_handle;
TIM_HandleTypeDef g_tim4_encoder2_handle;

encoder_speed encoder1_speed;
encoder_speed encoder2_speed;

void encoder1_tim3_init(void)
{
    TIM_Encoder_InitTypeDef sEncoderConfig = {0};

    g_tim3_encoder1_handle.Instance = TIM3;
    g_tim3_encoder1_handle.Init.Prescaler = 0;
    g_tim3_encoder1_handle.Init.CounterMode = TIM_COUNTERMODE_UP;
    g_tim3_encoder1_handle.Init.Period = 0xFFFF;
    g_tim3_encoder1_handle.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    g_tim3_encoder1_handle.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

    sEncoderConfig.EncoderMode = TIM_ENCODERMODE_TI12;

    sEncoderConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
    sEncoderConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
    sEncoderConfig.IC1Prescaler = TIM_ICPSC_DIV1;
    sEncoderConfig.IC1Filter = 6;

    sEncoderConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
    sEncoderConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
    sEncoderConfig.IC2Prescaler = TIM_ICPSC_DIV1;           //每个边沿都处理
    sEncoderConfig.IC2Filter = 6;

    HAL_TIM_Encoder_Init(&g_tim3_encoder1_handle,&sEncoderConfig);
    HAL_TIM_Encoder_Start(&g_tim3_encoder1_handle,TIM_CHANNEL_ALL);

    __HAL_TIM_SET_COUNTER(&g_tim3_encoder1_handle,0);

    encoder1_speed.encoder_last = (uint16_t)__HAL_TIM_GET_COUNTER(&g_tim3_encoder1_handle);
    encoder1_speed.encoder_diff = 0;
    encoder1_speed.motor_rps = 0.0f;
    encoder1_speed.motor_rpm = 0.0f;
}

void encoder2_tim4_init(void)
{
    TIM_Encoder_InitTypeDef sEncoderConfig = {0};

    g_tim4_encoder2_handle.Instance = TIM4;
    g_tim4_encoder2_handle.Init.Prescaler = 0;
    g_tim4_encoder2_handle.Init.CounterMode = TIM_COUNTERMODE_UP;
    g_tim4_encoder2_handle.Init.Period = 0xFFFF;
    g_tim4_encoder2_handle.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    g_tim4_encoder2_handle.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

    sEncoderConfig.EncoderMode = TIM_ENCODERMODE_TI12;

    sEncoderConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
    sEncoderConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
    sEncoderConfig.IC1Prescaler = TIM_ICPSC_DIV1;
    sEncoderConfig.IC1Filter = 6;

    sEncoderConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
    sEncoderConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
    sEncoderConfig.IC2Prescaler = TIM_ICPSC_DIV1;
    sEncoderConfig.IC2Filter = 6;

    HAL_TIM_Encoder_Init(&g_tim4_encoder2_handle,&sEncoderConfig);
    HAL_TIM_Encoder_Start(&g_tim4_encoder2_handle,TIM_CHANNEL_ALL);

    __HAL_TIM_SET_COUNTER(&g_tim4_encoder2_handle,0);

    encoder2_speed.encoder_last = (uint16_t)__HAL_TIM_GET_COUNTER(&g_tim4_encoder2_handle);
    encoder2_speed.encoder_diff = 0;
    encoder2_speed.motor_rps = 0.0f;
    encoder2_speed.motor_rpm = 0.0f;
}

void HAL_TIM_Encoder_MspInit(TIM_HandleTypeDef *htim)
{
    GPIO_InitTypeDef gpio_init_struct = {0};
    if(htim->Instance == TIM3)
    {
        __HAL_RCC_GPIOB_CLK_ENABLE();       //MOTOR1->ENCODER_A->PB4
        __HAL_RCC_GPIOC_CLK_ENABLE();       //MOTOR1->ENCODER_B->PC7
        __HAL_RCC_TIM3_CLK_ENABLE();

        gpio_init_struct.Pin = GPIO_PIN_4;
        gpio_init_struct.Mode = GPIO_MODE_AF_PP;
        gpio_init_struct.Pull = GPIO_PULLUP;
        gpio_init_struct.Speed = GPIO_SPEED_FREQ_HIGH;
        gpio_init_struct.Alternate = GPIO_AF2_TIM3;
        HAL_GPIO_Init(GPIOB,&gpio_init_struct);

        gpio_init_struct.Pin = GPIO_PIN_7;
        gpio_init_struct.Mode = GPIO_MODE_AF_PP;
        gpio_init_struct.Pull = GPIO_PULLUP;
        gpio_init_struct.Speed = GPIO_SPEED_FREQ_HIGH;
        gpio_init_struct.Alternate = GPIO_AF2_TIM3;
        HAL_GPIO_Init(GPIOC,&gpio_init_struct);
    }
    if(htim->Instance == TIM4)
    {
        __HAL_RCC_GPIOD_CLK_ENABLE();       //MOTOR2->ENCODER_A->PD12
        __HAL_RCC_TIM4_CLK_ENABLE();        //MOTOR2->ENCODER_B->PD13

        gpio_init_struct.Pin = GPIO_PIN_12 | GPIO_PIN_13;
        gpio_init_struct.Mode = GPIO_MODE_AF_PP;
        gpio_init_struct.Pull = GPIO_PULLUP;
        gpio_init_struct.Speed = GPIO_SPEED_FREQ_HIGH;
        gpio_init_struct.Alternate = GPIO_AF2_TIM4;
        HAL_GPIO_Init(GPIOD,&gpio_init_struct);
    }
}

int16_t motor1_encoder_speed_update(void)
{
    int16_t temp = 0;
    temp = __HAL_TIM_GET_COUNTER(&g_tim3_encoder1_handle);
    __HAL_TIM_SET_COUNTER(&g_tim3_encoder1_handle,0);
    return temp;
}

void motor2_encoder_speed_update(void)
{
    uint16_t now_cnt;
    now_cnt = (uint16_t)__HAL_TIM_GET_COUNTER(&g_tim4_encoder2_handle);
    encoder2_speed.encoder_diff = (int16_t)(now_cnt - encoder2_speed.encoder_last);
    encoder2_speed.encoder_last = now_cnt;

    encoder2_speed.motor_rps = (float)encoder2_speed.encoder_diff / (SAMPLE_TIME_S * GEAR_RATIO * ENCODER_PPR * ENCODER_X4);
    encoder2_speed.motor_rpm = encoder2_speed.motor_rps * 60.0f;
}
