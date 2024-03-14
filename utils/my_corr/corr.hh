// #include <stdio.h>
// #include <stdlib.h>
// #include <math.h>
// #include <vector>
// //#include <unistd.h> //windows中不存在，使用io.h和process.h替代
// #include <io.h>
// #include <process.h>
// //#include <sys/wait.h>
// #include <sys/types.h>
// #include <iostream>
// #include <windows.h>
// #include <vector>
// #include <algorithm>
// #include <numeric>
// #include <thread>
// #include <mutex>

#include <iostream>
#include <vector>
#include <algorithm>
#include <numeric>
#include <windows.h>




double mean(const std::vector<double>& data) {
    double sum = 0;
    int n=data.size();
    for (int i = 0; i < n; i++) {
        sum += data[i];
    }
    return sum / n;
}

double variance(const std::vector<double>& data, double mean) {
    double sum = 0;
    int n = data.size();
    for (int i = 0; i < n; i++) {
        sum += (data[i] - mean) * (data[i] - mean);
    }
    return sum / (n - 1);
}

double covariance(
    const std::vector<double>& data1, 
    const std::vector<double>& data2, 
    double mean1, double mean2) {
    
    double sum = 0;
    int n = data1.size();
    for (int i = 0; i < n; i++) {
        sum += (data1[i] - mean1) * (data2[i] - mean2);
    }
    return sum / (n - 1);
}

double correlation(const std::vector<double>& data1,const std::vector<double>& data2) {
    double mean1 = mean(data1);
    double mean2 = mean(data2);
    double var1 = variance(data1, mean1);
    double var2 = variance(data2, mean2);
    double cov = covariance(data1, data2, mean1, mean2);
    return cov / (sqrt(var1) * sqrt(var2));
}

// the struct to pass parameters to the child process
struct CHILD_PROCESS_PARAMS {
    int start;
    int end;
    const std::vector<std::vector<double>>* data;
    double* sum;
    int* count;
    HANDLE* hMutex;
};

DWORD WINAPI calc_corr_child(LPVOID lpParam) {
    CHILD_PROCESS_PARAMS* params = (CHILD_PROCESS_PARAMS*)lpParam;
    double local_sum = 0.0;
    int local_count = 0;
    for (int i = params->start; i <= params->end; i++) {
        for (int j = i + 1; j < params->data->size(); j++) {
            local_sum += correlation((*params->data)[i], (*params->data)[j]);
            local_count++;
        }
    }

    WaitForSingleObject(*params->hMutex, INFINITE);
    *params->sum += local_sum;
    *params->count += local_count;
    ReleaseMutex(*params->hMutex);

    delete params;
    return 0;
}

double calc_corr(const std::vector<std::vector<double>>& mv) {
    double sum_correlation = 0.0;
    int count = 0;
    int col = mv.size();

    // Create child processes
    const int NUM_PROCESSES = 10; // change this to the number of processes you want to create
    HANDLE hProcesses[NUM_PROCESSES];
    HANDLE hMutex = CreateMutex(NULL, FALSE, NULL);
    for (int i = 0; i < NUM_PROCESSES; i++) {
        int start = i * col / NUM_PROCESSES;
        int end = (i + 1) * col / NUM_PROCESSES - 1;
        CHILD_PROCESS_PARAMS* params = new CHILD_PROCESS_PARAMS;
        params->start = start;
        params->end = end;
        params->data = &mv;
        params->sum = &sum_correlation;
        params->count = &count;
        params->hMutex = &hMutex;
        hProcesses[i] = CreateThread(NULL, 0, calc_corr_child, (LPVOID)params, 0, NULL);
    }

    // Wait for child processes to finish
    WaitForMultipleObjects(NUM_PROCESSES, hProcesses, TRUE, INFINITE);
    CloseHandle(hMutex);

    // Compute average correlation
    double average_correlation = sum_correlation / count;
    return average_correlation;
}




