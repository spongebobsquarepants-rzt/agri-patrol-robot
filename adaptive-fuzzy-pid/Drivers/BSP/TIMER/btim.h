#ifndef __BTIM_H
#define __BTIM_H

#include "./SYSTEM/sys/sys.h"

void btim_tim6_int_init(uint16_t psc,uint16_t arr);
extern float output;
extern int32_t flag;
extern float current_temp;


#endif
