#include <cmath>
#include <omp.h> // openmp线程库

namespace itdog{
    inline double div(double x,double y){
        return x/y;
    }

    inline double sub(double x,double y){
        return x-y;
    }

    inline double add(double x,double y){
        return x+y;
    }

    inline double mul(double x,double y){
        return x*y;
    }


    inline double cal_max_drawdown_parallel(const double* arr, const int n) {
        double max_drawdown = 0.0;
        double cum_max = arr[0];
        double drawdown = 0.0;

        // #pragma omp parallel for reduction(max:max_drawdown)
        for (int i = 1; i < n; ++i) {
            double val = arr[i];
            if (val > cum_max) {
                cum_max = val;
                drawdown = 0.0;
            }
            else {
                drawdown = (cum_max - val) / cum_max;
                if (drawdown > max_drawdown) {
                    max_drawdown = drawdown;
                }
            }
        }

        return -1.0*max_drawdown;
    }

}
