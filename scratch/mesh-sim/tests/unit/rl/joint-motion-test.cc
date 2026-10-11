#include "src/rl/joint-motion.h"
#include <cassert>
#include <iostream>
using namespace mesh_sim;
int main()
{
    RlConfig b; b.x_min=0; b.x_max=10; b.y_min=0; b.y_max=10; b.unsafe_separation_m=1;
    assert(JointPathDistance({2,5,0},{4,0,0},{6,5,0},{-4,0,0},b,1) == 0);
    assert(JointPathDistance({2,5,10},{4,0,0},{6,5,0},{-4,0,0},b,1) == 10);
    assert(std::abs(JointPathDistance({9,5,0},{4,0,0},{10,7,0},{0,-2,0},b,1)) < 1e-8);
    std::vector<MotionPoint> p{{2,5,0},{6,5,0}}, v{{4,0,0},{-4,0,0}};
    auto r=RejectUnsafeJointMotion(p,v,{true,true},b,1);
    assert(r[0] && r[1] && v[0]==MotionPoint({0,0,0}) && v[1]==MotionPoint({0,0,0}));
    p={{2,5,0},{4,5,0},{6,5,0}};v={{2,0,0},{2,0,0},{0,0,0}};
    r=RejectUnsafeJointMotion(p,v,{true,true,true},b,1);
    assert(r[0] && r[1] && !r[2]);
    p={{2,5,0},{4,5,0}};v={{0,2,0},{0,2,0}};
    r=RejectUnsafeJointMotion(p,v,{true,true},b,1);
    assert(!r[0] && !r[1]);
    std::cout << "joint motion: crossing, altitude, wall clipping, cascade and safe motion passed\n";
}
