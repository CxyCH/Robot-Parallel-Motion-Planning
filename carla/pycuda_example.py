import pycuda
from pycuda.scan import ExclusiveScanKernel
import pycuda.autoinit
import pycuda.driver as drv
import pycuda.gpuarray as cuda
from pycuda.compiler import SourceModule

import numpy as np
import math

''''

'''

mod = SourceModule("""
    #include <stdio.h>

    __device__ bool check_col(float *y_vals,float *x_vals,float *obstacles, int num_obs){
        if (num_obs==0){
            return false;
        }
        for (int obs=0;obs<num_obs;obs++){
            for (int i=0;i<150;i++){
                float min_y = fmin(obstacles[obs*4 +3],obstacles[obs*4 +1]);
                float max_y = fmax(obstacles[obs*4 +3],obstacles[obs*4 +1]);
                float min_x = fmin(obstacles[obs*4],obstacles[obs*4 +2]);
                float max_x = fmax(obstacles[obs*4],obstacles[obs*4 +2]);
                if (max_y>=y_vals[i] && min_y<=y_vals[i]) {
                    if (max_x>=x_vals[i] && min_x<=x_vals[i]){
                        return true;
                    }
                }
            }
        }
        return false;
    }

    __device__ void RSRcost(float *curCost, float *parentCost, float *point1,float *point2, int r_min, float *obstacles, int num_obs){
        float PI = 3.141592653589793;

        float p_c1 [2] = { point1[0] + (r_min * cosf(point1[2] - PI/2)), point1[1] + (r_min * sinf(point1[2] - PI/2))}; 
        float p_c2 [2] = { point2[0] + (r_min * cosf(point2[2] - PI/2)), point2[1] + (r_min * sinf(point2[2] - PI/2))};

        float r_1 = sqrtf(powf(p_c1[0]-point1[0],2.0) + powf(p_c1[1]-point1[1],2.0));
        float r_2 = sqrtf(powf(p_c2[0]-point2[0],2.0) + powf(p_c2[1]-point2[1],2.0));

        float V1 [2] = {p_c2[0]-p_c1[0],p_c2[1]-p_c1[1]};

        float dist_centers = sqrtf(powf(V1[0],2) + powf(V1[1],2));

        float c = (r_1-r_2)/dist_centers;
        V1[0] /= dist_centers;
        V1[1] /= dist_centers;

        float normal [2] = {(V1[0]*c)-(V1[1]*sqrtf(1-powf(c,2))),(V1[0]*sqrtf(1-powf(c,2)))+(V1[1]*c)};

        if (isnan(normal[0])){
            return;
        }

        float tangent_1 [2] = {p_c1[0] + (r_1* normal[0]),p_c1[1] + (r_1* normal[1])};
        float tangent_2 [2] = {p_c2[0] + (r_2* normal[0]),p_c2[1] + (r_2* normal[1])};

        float V2 [2] = {tangent_2[0]-tangent_1[0],tangent_2[1]-tangent_1[1]};

        float p2_h [2] = {point1[0], point1[1]};
        float v1 [2] = {p2_h[0]-p_c1[0], p2_h[1]-p_c1[1]};
        float v2 [2] = {tangent_1[0]-p_c1[0], tangent_1[1]-p_c1[1]};

        float theta_1 = atan2f(v2[1],v2[0]) - atan2f(v1[1],v1[0]);

        if (theta_1>0){
            theta_1-=(PI*2);
        }

        float angle = point1[2] + (PI/2);

        float x_vals [150] = { };
        float y_vals [150] = { };
        float d_theta = theta_1/49;

        for (int i=0;i<50;i++){
            x_vals[i] = (abs(r_1) * cosf(angle+(i*d_theta))) + p_c1[0];
            y_vals[i] = (abs(r_1) * sinf(angle+(i*d_theta))) + p_c1[1];
        }

        float p3_h [2] = {point2[0], point2[1]};
        v1[0] = tangent_2[0]-p_c2[0];
        v1[1] = tangent_2[1]-p_c2[1];

        v2[0] = p3_h[0] - p_c2[0];
        v2[1] = p3_h[1] - p_c2[1];

        float theta_2 = atan2f(v2[1],v2[0]) - atan2f(v1[1],v1[0]);


        if (theta_2>0){
            theta_2-=(PI*2);
        }

        angle = atan2f((tangent_2[1]-p_c2[1]),(tangent_2[0]-p_c2[0]));

        d_theta = theta_2/49;

        for (int i=0;i<50;i++){
            x_vals[i+100] = (abs(r_2) * cosf(angle+(i*d_theta))) + p_c2[0];
            y_vals[i+100] = (abs(r_2) * sinf(angle+(i*d_theta))) + p_c2[1];
        }

        float d_x = (x_vals[100] - x_vals[49])/49;
        float d_y = (y_vals[100] - y_vals[49])/49;

        for (int i=0;i<50;i++){
            x_vals[i+50] = x_vals[49] + (i*d_x);
            y_vals[i+50] = y_vals[49] + (i*d_y);
        }

        // checks for collision

        bool collision = check_col(y_vals,x_vals,obstacles,num_obs);

        if (collision){
            return;
        }

        float cost = abs((r_1*theta_1)) + abs((r_2*theta_2)) + sqrtf(powf(V2[0],2) + powf(V2[1],2));
        cost += *parentCost;

        if (cost> *curCost){
            return;
        }

        *curCost = cost;
        return;
    }

    __device__ void LSLcost(float *curCost, float *parentCost, float *point1,float *point2, int r_min, float *obstacles, int num_obs){
        float PI = 3.141592653589793;

        float p_c1 [2] = { point1[0] + (r_min * cosf(point1[2] + PI/2)), point1[1] + (r_min * sinf(point1[2] + PI/2))}; 
        float p_c2 [2] = { point2[0] + (r_min * cosf(point2[2] + PI/2)), point2[1] + (r_min * sinf(point2[2] + PI/2))};

        float r_1 = -1.0 * sqrtf(powf(p_c1[0]-point1[0],2.0) + powf(p_c1[1]-point1[1],2.0));
        float r_2 = -1.0 * sqrtf(powf(p_c2[0]-point2[0],2.0) + powf(p_c2[1]-point2[1],2.0));

        float V1 [2] = {p_c2[0]-p_c1[0],p_c2[1]-p_c1[1]};

        float dist_centers = sqrtf(powf(V1[0],2) + powf(V1[1],2));

        float c = (r_1-r_2)/dist_centers;
        V1[0] /= dist_centers;
        V1[1] /= dist_centers;

        float normal [2] = {(V1[0]*c)-(V1[1]*sqrtf(1-powf(c,2))),(V1[0]*sqrtf(1-powf(c,2)))+(V1[1]*c)};

        if (isnan(normal[0])){
            return;
        }

        float tangent_1 [2] = {p_c1[0] + (r_1* normal[0]),p_c1[1] + (r_1* normal[1])};
        float tangent_2 [2] = {p_c2[0] + (r_2* normal[0]),p_c2[1] + (r_2* normal[1])};

        float V2 [2] = {tangent_2[0]-tangent_1[0],tangent_2[1]-tangent_1[1]};

        float p2_h [2] = {point1[0], point1[1]};
        float v1 [2] = {p2_h[0]-p_c1[0], p2_h[1]-p_c1[1]};
        float v2 [2] = {tangent_1[0]-p_c1[0], tangent_1[1]-p_c1[1]};

        float theta_1 = atan2f(v2[1],v2[0]) - atan2f(v1[1],v1[0]);

        if (theta_1<0){
            theta_1+=(PI*2);
        }

        float angle = point1[2] - (PI/2);

        float x_vals [150] = { };
        float y_vals [150] = { };
        float d_theta = theta_1/49;

        for (int i=0;i<50;i++){
            x_vals[i] = (abs(r_1) * cosf(angle+(i*d_theta))) + p_c1[0];
            y_vals[i] = (abs(r_1) * sinf(angle+(i*d_theta))) + p_c1[1];
        }

        float p3_h [2] = {point2[0], point2[1]};
        v1[0] = tangent_2[0]-p_c2[0];
        v1[1] = tangent_2[1]-p_c2[1];

        v2[0] = p3_h[0] - p_c2[0];
        v2[1] = p3_h[1] - p_c2[1];

        float theta_2 = atan2f(v2[1],v2[0]) - atan2f(v1[1],v1[0]);

        if (theta_2<0){
            theta_2+=(PI*2);
        }
        angle = atan2f((tangent_2[1]-p_c2[1]),(tangent_2[0]-p_c2[0]));

        d_theta = theta_2/49;

        for (int i=0;i<50;i++){
            x_vals[i+100] = (abs(r_2) * cosf(angle+(i*d_theta))) + p_c2[0];
            y_vals[i+100] = (abs(r_2) * sinf(angle+(i*d_theta))) + p_c2[1];
        }

        float d_x = (x_vals[100] - x_vals[49])/49;
        float d_y = (y_vals[100] - y_vals[49])/49;

        for (int i=0;i<50;i++){
            x_vals[i+50] = x_vals[49] + (i*d_x);
            y_vals[i+50] = y_vals[49] + (i*d_y);
        }

        bool collision = check_col(y_vals,x_vals,obstacles,num_obs);

        if (collision){
            return;
        }

        float cost = abs((r_1*theta_1)) + abs((r_2*theta_2)) + sqrtf(powf(V2[0],2) + powf(V2[1],2));
        cost += *parentCost;

        if (cost> *curCost){
            return;
        }

        *curCost = cost;
        return;
    }

    __device__ void LSRcost(float *curCost, float *parentCost, float *point1,float *point2, int r_min, float *obstacles, int num_obs){
        float PI = 3.141592653589793;

        float p_c1 [2] = { point1[0] + (r_min * cosf(point1[2] + PI/2)), point1[1] + (r_min * sinf(point1[2] + PI/2))}; 
        float p_c2 [2] = { point2[0] + (r_min * cosf(point2[2] - PI/2)), point2[1] + (r_min * sinf(point2[2] - PI/2))};

        float r_1 = -1.0 * sqrtf(powf(p_c1[0]-point1[0],2.0) + powf(p_c1[1]-point1[1],2.0));
        float r_2 = sqrtf(powf(p_c2[0]-point2[0],2.0) + powf(p_c2[1]-point2[1],2.0));

        float V1 [2] = {p_c2[0]-p_c1[0],p_c2[1]-p_c1[1]};

        float dist_centers = sqrtf(powf(V1[0],2) + powf(V1[1],2));

        float c = (r_1-r_2)/dist_centers;
        V1[0] /= dist_centers;
        V1[1] /= dist_centers;

        float normal [2] = {(V1[0]*c)-(V1[1]*sqrtf(1-powf(c,2))),(V1[0]*sqrtf(1-powf(c,2)))+(V1[1]*c)};

        if (isnan(normal[0])){
            return;
        }

        float tangent_1 [2] = {p_c1[0] + (r_1* normal[0]),p_c1[1] + (r_1* normal[1])};
        float tangent_2 [2] = {p_c2[0] + (r_2* normal[0]),p_c2[1] + (r_2* normal[1])};

        float V2 [2] = {tangent_2[0]-tangent_1[0],tangent_2[1]-tangent_1[1]};

        float p2_h [2] = {point1[0], point1[1]};
        float v1 [2] = {p2_h[0]-p_c1[0], p2_h[1]-p_c1[1]};
        float v2 [2] = {tangent_1[0]-p_c1[0], tangent_1[1]-p_c1[1]};

        float theta_1 = atan2f(v2[1],v2[0]) - atan2f(v1[1],v1[0]);

        if (theta_1<0){
            theta_1+=(PI*2);
        }

        float angle = point1[2] - (PI/2);

        float x_vals [150] = { };
        float y_vals [150] = { };
        float d_theta = theta_1/49;

        for (int i=0;i<50;i++){
            x_vals[i] = (abs(r_1) * cosf(angle+(i*d_theta))) + p_c1[0];
            y_vals[i] = (abs(r_1) * sinf(angle+(i*d_theta))) + p_c1[1];
        }


        float p3_h [2] = {point2[0], point2[1]};
        v1[0] = tangent_2[0]-p_c2[0];
        v1[1] = tangent_2[1]-p_c2[1];

        v2[0] = p3_h[0] - p_c2[0];
        v2[1] = p3_h[1] - p_c2[1];

        float theta_2 = atan2f(v2[1],v2[0]) - atan2f(v1[1],v1[0]);

        if (theta_2>0){
            theta_2-=(PI*2);
        }

        angle = atan2f((tangent_2[1]-p_c2[1]),(tangent_2[0]-p_c2[0]));

        d_theta = theta_2/49;

        for (int i=0;i<50;i++){
            x_vals[i+100] = (abs(r_2) * cosf(angle+(i*d_theta))) + p_c2[0];
            y_vals[i+100] = (abs(r_2) * sinf(angle+(i*d_theta))) + p_c2[1];
        }

        float d_x = (x_vals[100] - x_vals[49])/49;
        float d_y = (y_vals[100] - y_vals[49])/49;

        for (int i=0;i<50;i++){
            x_vals[i+50] = x_vals[49] + (i*d_x);
            y_vals[i+50] = y_vals[49] + (i*d_y);
        }

        bool collision = check_col(y_vals,x_vals,obstacles,num_obs);

        if (collision){
            return;
        }

        float cost = abs((r_1*theta_1)) + abs((r_2*theta_2)) + sqrtf(powf(V2[0],2) + powf(V2[1],2));
        cost += *parentCost;

        if (cost> *curCost){
            return;
        }

        *curCost = cost;
        return;
    }

    __device__ void RSLcost(float *curCost, float *parentCost, float *point1, float *point2, int r_min, float *obstacles, int num_obs){
        float PI = 3.141592653589793;

        float p_c1 [2] = { point1[0] + (r_min * cosf(point1[2] - PI/2)), point1[1] + (r_min * sinf(point1[2] - PI/2))}; 
        float p_c2 [2] = { point2[0] + (r_min * cosf(point2[2] + PI/2)), point2[1] + (r_min * sinf(point2[2] + PI/2))};

        float r_1 = sqrtf(powf(p_c1[0]-point1[0],2.0) + powf(p_c1[1]-point1[1],2.0));
        float r_2 = -1.0 * sqrtf(powf(p_c2[0]-point2[0],2.0) + powf(p_c2[1]-point2[1],2.0));

        float V1 [2] = {p_c2[0]-p_c1[0],p_c2[1]-p_c1[1]};

        float dist_centers = sqrtf(powf(V1[0],2) + powf(V1[1],2));

        float c = (r_1-r_2)/dist_centers;
        V1[0] /= dist_centers;
        V1[1] /= dist_centers;

        float normal [2] = {(V1[0]*c)-(V1[1]*sqrtf(1-powf(c,2))),(V1[0]*sqrtf(1-powf(c,2)))+(V1[1]*c)};

        if (isnan(normal[0])){
            return;
        }

        float tangent_1 [2] = {p_c1[0] + (r_1* normal[0]),p_c1[1] + (r_1* normal[1])};
        float tangent_2 [2] = {p_c2[0] + (r_2* normal[0]),p_c2[1] + (r_2* normal[1])};

        float V2 [2] = {tangent_2[0]-tangent_1[0],tangent_2[1]-tangent_1[1]};

        float p2_h [2] = {point1[0], point1[1]};
        float v1 [2] = {p2_h[0]-p_c1[0], p2_h[1]-p_c1[1]};
        float v2 [2] = {tangent_1[0]-p_c1[0], tangent_1[1]-p_c1[1]};

        float theta_1 = atan2f(v2[1],v2[0]) - atan2f(v1[1],v1[0]);

        if (theta_1>0){
            theta_1-=(PI*2);
        }

        float angle = point1[2] + (PI/2);

        float x_vals [150] = { };
        float y_vals [150] = { };
        float d_theta = theta_1/49;

        for (int i=0;i<50;i++){
            x_vals[i] = (abs(r_1) * cosf(angle+(i*d_theta))) + p_c1[0];
            y_vals[i] = (abs(r_1) * sinf(angle+(i*d_theta))) + p_c1[1];
        }

        float p3_h [2] = {point2[0], point2[1]};
        v1[0] = tangent_2[0]-p_c2[0];
        v1[1] = tangent_2[1]-p_c2[1];

        v2[0] = p3_h[0] - p_c2[0];
        v2[1] = p3_h[1] - p_c2[1];

        float theta_2 = atan2f(v2[1],v2[0]) - atan2f(v1[1],v1[0]);

        if (theta_2<0){
            theta_2+=(PI*2);
        }

        angle = atan2f((tangent_2[1]-p_c2[1]),(tangent_2[0]-p_c2[0]));

        d_theta = theta_2/49;

        for (int i=0;i<50;i++){
            x_vals[i+100] = (abs(r_2) * cosf(angle+(i*d_theta))) + p_c2[0];
            y_vals[i+100] = (abs(r_2) * sinf(angle+(i*d_theta))) + p_c2[1];
        }

        float d_x = (x_vals[100] - x_vals[49])/49;
        float d_y = (y_vals[100] - y_vals[49])/49;

        for (int i=0;i<50;i++){
            x_vals[i+50] = x_vals[49] + (i*d_x);
            y_vals[i+50] = y_vals[49] + (i*d_y);
        }

        bool collision = check_col(y_vals,x_vals,obstacles,num_obs);

        if (collision){
            return;
        }

        float cost = abs((r_1*theta_1)) + abs((r_2*theta_2)) + sqrtf(powf(V2[0],2) + powf(V2[1],2));
        cost += *parentCost;

        if (cost > *curCost){
            return;
        }

        *curCost = cost;
        return;
    }

    __device__ bool computeDubinsCost(float &cost, float &parentCost, float *end_point, float *start_point, float r_min, float *obstacles, int num_obs){
        float curCost = cost;

        RSRcost(&curCost, &parentCost, start_point, end_point, r_min, obstacles, num_obs);
        LSLcost(&curCost, &parentCost, start_point, end_point, r_min, obstacles, num_obs);
        LSRcost(&curCost, &parentCost, start_point, end_point, r_min, obstacles, num_obs);
        RSLcost(&curCost, &parentCost, start_point, end_point, r_min, obstacles, num_obs);


        bool connected = curCost < cost;
        cost = connected ? curCost : cost;
        return connected;
    }

    __global__ void dubinConnection(float *cost, int *parent, int *x, int *y, float *states, int *open, int *unexplored, const int *xSize, const int *ySize, float *obstacles, int *num_obs, float *radius){
        const int index = threadIdx.x + (blockIdx.x * blockDim.x);
        if(index >= xSize[0]){
            return;
        }

        for(int i=0; i < ySize[0]; i++){
            bool connected = computeDubinsCost(cost[x[index]], cost[y[i]], &states[x[index]*3], &states[y[i]*3], radius[0], obstacles, num_obs[0]);

            parent[x[index]] = connected ? y[i]: parent[x[index]];
            cost[x[index]] = connected ? cost[y[i]] + cost[x[index]] : cost[x[index]];
            open[x[index]] = connected ? 1 : open[x[index]];
            open[y[i]] = connected ? 0 : open[y[i]];
            unexplored[x[index]] = connected ? 0 : unexplored[x[index]];
        }
    }

    __global__ void wavefront(int *G, int *open, float *cost, float *threshold, const int *n){
        const int index = threadIdx.x + (blockIdx.x * blockDim.x);
        if(index >= n[0]){
            return;
        }
        
        G[index] = open[index] && cost[index] <= threshold[0] ? 1 : 0;
    }

    __global__ void neighborIndicator(int *x_indicator, int *G, int *unexplored, int *neighbors, int *num_neighbors, int *neighbors_index, const int *n){
        const int index = threadIdx.x + (blockIdx.x * blockDim.x);
        if(index >= n[0]){
            return;
        }

        for(int i=0; i < num_neighbors[G[index]]; i++){
            int j = neighbors[neighbors_index[G[index]] + i];
            x_indicator[j] = unexplored[j] || x_indicator[j] > 0 ? 1 : 0;
        }      
    }

    __global__ void compact(int *x, int *scan, int *indicator, int *waypoints, const int *n){
        const int index = threadIdx.x + (blockIdx.x * blockDim.x);
        if(index >= n[0]){
            return;
        }

        if(indicator[index] == 1){
            x[scan[index]] = waypoints[index];
        }
    }
""")

wavefront = mod.get_function("wavefront")
neighborIndicator = mod.get_function("neighborIndicator")
exclusiveScan = ExclusiveScanKernel(np.int32, "a+b", 0)
compact = mod.get_function("compact")
dubinConnection = mod.get_function("dubinConnection")

class GMT(object):
    def __init__(self, init_parameters, debug=False):
        self._cpu_init(init_parameters, debug)
        self._gpu_init(debug)

        self.route = []
        self.start = 0

    def _cpu_init(self, init_parameters, debug):
        self.states = init_parameters['states']
        self.n = self.states.shape[0]
        self.waypoints = np.arange(self.n).astype(np.int32)

        self.neighbors = init_parameters['neighbors']
        self.num_neighbors = init_parameters['num_neighbors']

        self.cost = np.full(self.n, np.inf).astype(np.float32)
        self.Vunexplored = np.full(self.n, 1).astype(np.int32)
        self.Vopen = np.zeros_like(self.Vunexplored).astype(np.int32)
        
        if debug:
            print('neighbors: ', self.neighbors)

    def _gpu_init(self, debug):
        self.dev_states = cuda.to_gpu(self.states)
        self.dev_waypoints = cuda.to_gpu(self.waypoints)

        self.dev_n = cuda.to_gpu(np.array([self.n]).astype(np.int32))

        self.dev_neighbors = cuda.to_gpu(self.neighbors)
        self.dev_num_neighbors = cuda.to_gpu(self.num_neighbors)
        self.neighbors_index = cuda.to_gpu(self.num_neighbors)
        exclusiveScan(self.neighbors_index)

    def step_init(self, iter_parameters, debug):
        self.cost[self.start] = np.inf
        self.Vunexplored[self.start] = 1
        self.Vopen[self.start] = 0

        self.obstacles = iter_parameters['obstacles']
        self.num_obs = iter_parameters['num_obs']
        self.parent = np.full(self.n, -1).astype(np.int32)

        self.start = iter_parameters['start']
        self.goal = iter_parameters['goal']
        self.radius = iter_parameters['radius']
        self.threshold = np.array([ iter_parameters['threshold'] ]).astype(np.float32)


        self.cost[self.start] = 0
        self.Vunexplored[self.start] = 0
        self.Vopen[self.start] = 1

        if debug:
            print('parents:', self.parent)
            print('cost: ', self.cost)
            print('Vunexplored: ', self.Vunexplored)
            print('Vopen: ', self.Vopen)

        self.dev_radius = cuda.to_gpu(np.array([self.radius]).astype(np.float32))
        self.dev_threshold = cuda.to_gpu(self.threshold)

        self.dev_obstacles = cuda.to_gpu(self.obstacles) 
        self.dev_num_obs = cuda.to_gpu(self.num_obs)

        self.dev_parent = cuda.to_gpu(self.parent)
        self.dev_cost = cuda.to_gpu(self.cost)

        self.dev_open = cuda.to_gpu(self.Vopen)
        self.dev_unexplored = cuda.to_gpu(self.Vunexplored)

    def get_path(self):
        p = self.goal
        while p != -1:
            self.route.append(p)
            p = self.parent[p]

        # del self.route[-1]

    def run_step(self, iter_parameters, iter_limit=1000, debug=False):
        self.step_init(iter_parameters,debug)

        goal_reached = False
        iteration = 0
        threadsPerBlock = 128
        while True:
            iteration += 1

            ########## create Wave front ###############
            dev_Gindicator = cuda.zeros_like(self.dev_open, dtype=np.int32)

            nBlocksPerGrid = int(((self.n + threadsPerBlock - 1) / threadsPerBlock))
            wavefront(dev_Gindicator, self.dev_open, self.dev_cost, self.dev_threshold, self.dev_n, block=(threadsPerBlock,1,1), grid=(nBlocksPerGrid,1))
            self.dev_threshold += self.dev_threshold
            goal_reached = dev_Gindicator[self.goal].get() == 1
            
            dev_Gscan = cuda.to_gpu(dev_Gindicator)
            exclusiveScan(dev_Gscan)
            dev_gSize = dev_Gscan[-1] + dev_Gindicator[-1]
            gSize = int(dev_gSize.get())

            ######### scan and compact open set to connect neighbors ###############
            dev_yscan = cuda.to_gpu(self.dev_open)
            exclusiveScan(dev_yscan)
            dev_ySize = dev_yscan[-1] + self.dev_open[-1]
            ySize = int(dev_ySize.get())

            dev_y = cuda.zeros(ySize, dtype=np.int32)
            compact(dev_y, dev_yscan, self.dev_open, self.dev_waypoints, self.dev_n, block=(threadsPerBlock,1,1), grid=(nBlocksPerGrid,1))

            if ySize == 0:
                print('### empty open set ###')
                # del self.route[-1]
                return self.route
            elif iteration >= iter_limit:
                print('### iteration limit ###')
                # del self.route[-1]
                return self.route
            elif goal_reached:
                print('### goal reached ###')
                self.parent = self.dev_parent.get()
                self.get_path()
                return self.route
            elif gSize == 0:
                print('### threshold skip')
                continue

            dev_G = cuda.zeros(gSize, dtype=np.int32)
            compact(dev_G, dev_Gscan, dev_Gindicator, self.dev_waypoints, self.dev_n, block=(threadsPerBlock,1,1), grid=(nBlocksPerGrid,1))     

            ########## creating neighbors of wave front to connect open ###############
            dev_xindicator = cuda.zeros_like(self.dev_open, dtype=np.int32)
            gBlocksPerGrid = int(((gSize + threadsPerBlock - 1) / threadsPerBlock))
            neighborIndicator(dev_xindicator, dev_G, self.dev_unexplored, self.dev_neighbors, self.dev_num_neighbors, self.neighbors_index, dev_gSize, block=(threadsPerBlock,1,1), grid=(gBlocksPerGrid,1))

            dev_xscan = cuda.to_gpu(dev_xindicator)
            exclusiveScan(dev_xscan)
            dev_xSize = dev_xscan[-1] + dev_xindicator[-1]
            xSize = int(dev_xSize.get())

            if xSize == 0:
                print('### x skip')
                continue

            dev_x = cuda.zeros(xSize, dtype=np.int32)
            compact(dev_x, dev_xscan, dev_xindicator, self.dev_waypoints, self.dev_n, block=(threadsPerBlock,1,1), grid=(nBlocksPerGrid,1))

            ######### connect neighbors ####################
            # # launch planning
            xBlocksPerGrid = int(((xSize + threadsPerBlock - 1) / threadsPerBlock))
            dubinConnection(self.dev_cost, self.dev_parent, dev_x, dev_y, self.dev_states, self.dev_open, self.dev_unexplored, dev_xSize, dev_ySize, self.dev_obstacles, self.dev_num_obs, self.dev_radius, block=(threadsPerBlock,1,1), grid=(xBlocksPerGrid,1))

            if debug:
                print('dev parents:', self.dev_parent)
                print('dev cost: ', self.dev_cost)
                print('dev unexplored: ', self.dev_unexplored)
                print('dev open: ', self.dev_open)
                print('dev threshold: ', self.dev_threshold)

                print('goal reached: ', goal_reached)
                print('y size: ', ySize, 'y: ' , dev_y)
                print('G size: ', gSize, 'G: ', dev_G)

                print('x size: ', dev_xSize, 'x: ', dev_x)
                print('######### iteration: ', iteration)


if __name__ == '__main__':
    states = np.array([[10,2,-135*np.pi/180], [10,2,0*np.pi/180], [10,2,45*np.pi/180], # 0-2
        [8,5,-135*np.pi/180], [8,5,90*np.pi/180], [8,5,45*np.pi/180], # 3-5
        [12,6,-135*np.pi/180], [12,6,90*np.pi/180], [12,6,45*np.pi/180], # 6-8
        [11,8,-135*np.pi/180], [11,8,90*np.pi/180], [11,8,45*np.pi/180], # 9-11
        [2,7,-135*np.pi/180], [2,7,90*np.pi/180], [2,7,45*np.pi/180], # 12-14
        [5,10,-135*np.pi/180], [5,10,90*np.pi/180], [5,10,45*np.pi/180]]).astype(np.float32) #15-17

    n0 = [3,4,5,6,7,8]
    n1 = [0,1,2,9,10,11,12,13,14,15,16,17]
    n2 = [3,4,5,9,10,11]
    n3 = [3,4,5,6,7,8,15,16,17]
    n4 = [3,4,5,15,16,17]
    n5 = [3,4,5,9,10,11,12,13,14]
    nn = 3*n0 + 3*n1 + 3*n2 + 3*n3 + 3*n4 + 3*n5

    neighbors = np.array(nn).astype(np.int32)
    num_neighbors = np.array([len(n0),len(n0),len(n0), len(n1),len(n1),len(n1), len(n2),len(n2),len(n2), len(n3),len(n3),len(n3), len(n4),len(n4),len(n4), len(n5),len(n5),len(n5)]).astype(np.int32)

    obstacles = np.array([[7,6,4,9]]).astype(np.float32)
    num_obs = np.array([1]).astype(np.int32)

    start = 1
    goal = 12
    radius = 2
    threshold = 10

    init_parameters = {'states':states, 'neighbors':neighbors, 'num_neighbors':num_neighbors}
    iter_parameters = {'start':start, 'goal':goal, 'radius':radius, 'threshold':threshold, 'obstacles':obstacles, 'num_obs':num_obs}

    gmt = GMT(init_parameters, debug=True)
    route = gmt.run_step(iter_parameters, iter_limit=8, debug=True)
    print(route)