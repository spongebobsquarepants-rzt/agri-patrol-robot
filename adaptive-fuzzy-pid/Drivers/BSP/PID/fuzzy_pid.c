#include "./BSP/PID/fuzzy_pid.h"
#include "./BSP/PID/pid.h"
#include <math.h>


static const float g_rule_table_kp[FUZZY_SET_SIZE][FUZZY_SET_SIZE] =
{
    /* ec:    NB,   NM,   NS,   ZO,   PS,   PM,   PB */
    /* e=NB */ {PB,  PB,  PM,  PM,  PM,  ZO,  ZO},
    /* e=NM */ {PB,  PB,  PM,  PS,  PS,  ZO,  NS},
    /* e=NS */ {PM,  PM,  PM,  PS,  ZO,  NS,  NS},
    /* e=ZO */ {PM,  PM,  PS,  ZO,  NS,  NM,  NM},
    /* e=PS */ {PS,  PS,  ZO,  NS,  NS,  NM,  NM},
    /* e=PM */ {PS,  ZO,  NS,  NM,  NM,  NM,  NB},
    /* e=PB */ {ZO,  ZO,  NM,  NM,  NM,  NB,  NB}
};

static const float g_rule_table_ki[FUZZY_SET_SIZE][FUZZY_SET_SIZE] =
{
    /* ec:    NB,   NM,   NS,   ZO,   PS,   PM,   PB */
    /* e=NB */ {NB,  NB,  NM,  NM,  NS,  ZO,  ZO},
    /* e=NM */ {NB,  NB,  NM,  NS,  NS,  ZO,  ZO},
    /* e=NS */ {NB,  NM,  NS,  NS,  ZO,  PS,  PS},
    /* e=ZO */ {NM,  NM,  NS,  ZO,  PS,  PM,  PM},
    /* e=PS */ {NM,  NS,  ZO,  PS,  PS,  PB,  PB},
    /* e=PM */ {ZO,  ZO,  PS,  PS,  PM,  PB,  PB},
    /* e=PB */ {ZO,  ZO,  PS,  PM,  PM,  PB,  PB}
};

static const float g_rule_table_kd[FUZZY_SET_SIZE][FUZZY_SET_SIZE] =
{
    /* ec:    NB,   NM,   NS,   ZO,   PS,   PM,   PB */
    /* e=NB */ {PB,  PB,  PM,  PS,  ZO,  NS,  NM},
    /* e=NM */ {PB,  PB,  PM,  PS,  ZO,  NS,  NM},
    /* e=NS */ {PM,  PM,  PS,  ZO,  NS,  NM,  NM},
    /* e=ZO */ {PS,  PS,  ZO,  NS,  NS,  NM,  NM},
    /* e=PS */ {ZO,  ZO,  NS,  NM,  NM,  NB,  NB},
    /* e=PM */ {NS,  NS,  NM,  NB,  NB,  NB,  NB},
    /* e=PB */ {NM,  NM,  NB,  NB,  NB,  NB,  NB}
};

/*限幅函数，将映射到模糊论域的误差e限制在 min-max的模糊论域*/
static float constrain(float value,float min,float max)
{
    if(value < min) return min;
    if(value > max) return max;
    return value;
}

/*    分化隶属度函数
    找到输出x属于哪个区间，定位其在模糊数组位置，确定隶属度

    crisp_input:已经模糊化的输入,范围[-3,3];
    mf_outputs[FUZZY_SET_SIZE] 即为隶属度数组，除区间外两个值其余均为零
*/
static void fuzzify_input(float crisp_input,float mf_outputs[FUZZY_SET_SIZE])
{
    float x = constrain(crisp_input,-3.0f,3.0f);

    for(int8_t i = 0;i < FUZZY_SET_SIZE;i++)        //隶属度清零
    {
        mf_outputs[i] = 0.0f;
    }

    int8_t i = (int8_t)floorf(x);   //对x向下取整，找到左边的中心点，即左边那个模糊中心点的值
    float c_i = (float)i;           //左边中心点
    float c_i_plus_1 = c_i + 1.0f;  //加一即右边中心点
    
    int8_t index_i = i + 3;         //左边中心点在模糊规则表里面的坐标
    int8_t index_i_plus = i + 4;    //右边中心点在数组里的坐标

    if(index_i >= 0 && index_i < FUZZY_SET_SIZE)    //边界保护
    {
        mf_outputs[index_i] = c_i_plus_1 - x;       //x = 0.75,c_i = 0,c_i_plus = 1,即输入x对左边模糊集的隶属度，填入隶属数组
    }

    if(index_i_plus >= 0 && index_i_plus < FUZZY_SET_SIZE)
    {
        mf_outputs[index_i_plus] = x - c_i;         //即输入x对右边模糊集的隶属度
    }

    if(x == 3.0f)
    {
        mf_outputs[6] = 1.0f;
        mf_outputs[5] = 0.0f;
    }
    if(x == -3.0f)
    {
        mf_outputs[0] = 1.0f;
        mf_outputs[1] = 0.0f;
    }
}

/*       模糊推理和解模糊函数
    e_mf[FUZZY_SET_SIZE]:误差e模糊化后的七个隶属度
    ec_mf[FUZZY_SET_SIZE]:误差变化率模糊化后的七个隶属度
    *rule_table:规则表指针  ->g_rule_table_kp
                           ->g_rule_table_ki
                           ->g_rule_table_kd 

    返回值：得到的值任然再模糊域里面,还需要再乘一个缩放因子才能直接作用于现实中的PID控制器
*/
static float defuzzify(const float e_mf[FUZZY_SET_SIZE],
                       const float ec_mf[FUZZY_SET_SIZE],
                       const float *rule_table)
{
    float weighted_sum = 0.0f;
    float activation_sum = 0.0f;

    for(int8_t i = 0;i < FUZZY_SET_SIZE;i++)
    {
        if(e_mf[i] == 0.0f)
        {
            continue;;
        }

        for(int8_t j = 0.0f;j < FUZZY_SET_SIZE;j++)
        {
            if(ec_mf[j] == 0.0f)
            {
                continue;
            }

            float activation = (e_mf[i] < ec_mf[j]) ? e_mf[i] : ec_mf[j];

            if(activation == 0.0f)
            {
                continue;
            }

            float rule_output_center = rule_table[i * FUZZY_SET_SIZE + j];

            weighted_sum = weighted_sum + activation * rule_output_center;
            activation_sum = activation_sum + activation;
        }
    }

    if(activation_sum == 0.0f)
    {
        return 0.0f;
    }

    return weighted_sum / activation_sum;
}

/*      保存缩放参数
        保存输出缩放参数
        把三张规则表挂进结构体

*/
void fuzzy_pid_init(FuzzyPID_t *fuzzy,
                    float ke,float kec,
                    float kp_out,float ki_out,float kd_out)
{
    fuzzy->Ke = ke;
    fuzzy->Kec = kec;
    fuzzy->ke_last = 0.0f;

    fuzzy->Kp_out = kp_out;
    fuzzy->Ki_out = ki_out;
    fuzzy->Kd_out = kd_out;

    fuzzy->rule_table_kp = (const float *)g_rule_table_kp;
    fuzzy->rule_table_ki = (const float *)g_rule_table_ki;
    fuzzy->rule_table_kd = (const float *)g_rule_table_kd;
}


void fuzzy_pid_calculate(FuzzyPID_t *fuzzy,
                         float e,float ec,
                         float *delta_kp,
                         float *delta_ki,
                         float *delta_kd)
{
    float e_scaled = fuzzy->Ke * e;         //ke = 3/e_max
    float ec_scaled = fuzzy->Kec * ec;      //将误差和误差变化率映射到模糊论域

    float e_mf[FUZZY_SET_SIZE];             //隶属度数组
    float ec_mf[FUZZY_SET_SIZE];
    fuzzify_input(e_scaled,e_mf);
    fuzzify_input(ec_scaled,ec_mf);         //对e、ec分化隶属度

    float dkp_crisp = defuzzify(e_mf,ec_mf,fuzzy->rule_table_kp);   //分别解模糊
    float dki_crisp = defuzzify(e_mf,ec_mf,fuzzy->rule_table_ki);
    float dkd_crisp = defuzzify(e_mf,ec_mf,fuzzy->rule_table_kd);

    *delta_kp = fuzzy->Kp_out * dkp_crisp;
    *delta_ki = fuzzy->Ki_out * dki_crisp;
    *delta_kd = fuzzy->Kd_out * dkd_crisp;
}
/*      模糊pid更新于基本pid控制器
    fuzzy:模糊pid参数储存
    pid:普通pid参数储存
    Pidparams_t：保存一份原始pid原始参数

*/
float fuzzy_pid_calculate_output(FuzzyPID_t *fuzzy,PID_t *pid,const Pidparams_t *base_params,float current)
{
    float e;
    float ec;
    float delta_kp = 0.0f;
    float delta_ki = 0.0f;
    float delta_kd = 0.0f;

    e = pid->target - current;
    ec = e - fuzzy->ke_last;

    fuzzy_pid_calculate(fuzzy,e,ec,&delta_kp,&delta_ki,&delta_kd);
    fuzzy->ke_last = e;

    pid->kp = base_params->kp + delta_kp;
    pid->ki = base_params->ki + delta_ki;
    pid->kd = base_params->kd + delta_kd;

    if(pid->kp < 0.0f) pid->kp = 0.0f;
    if(pid->ki < 0.0f) pid->ki = 0.0f;
    if(pid->kd < 0.0f) pid->kd = 0.0f;

    return pid_calculate(pid,current);
}
