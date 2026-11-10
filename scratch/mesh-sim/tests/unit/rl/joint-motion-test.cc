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
    p = {{2, 5, 0}, {4, 5, 0}};
    v = {{4, 0, 0}, {0, 0, 0}};
    r = RejectUnsafeJointMotion(p, v, {true, false}, b, 1, {true, false});
    assert(!r[0] && !r[1] && v[0] == MotionPoint({4, 0, 0}));
    BuildingSpec box;
    box.x_min = 10;
    box.x_max = 30;
    box.y_min = 10;
    box.y_max = 30;
    box.z_min = 0;
    box.z_max = 8;
    assert(SegmentIntersectsBuilding({5, 20, 1.5}, {35, 20, 1.5}, box, 2));
    assert(!SegmentIntersectsBuilding({5, 20, 20}, {35, 20, 20}, box, 2));
    assert(SegmentIntersectsBuilding({5, 20, 9}, {35, 20, 9}, box, 2));
    box.z_max = 38;
    assert(SegmentIntersectsBuilding({5, 20, 20}, {35, 20, 20}, box, 2));
    assert(!SegmentIntersectsBuilding({5, 5, 1.5}, {10, 35, 1.5}, box, 0));
    std::cout << "joint motion: crossing, altitude, wall clipping, cascade and safe motion passed\n";
}
