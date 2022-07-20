from typing import Tuple, Annotated, Dict
from .world.abstracts import VTObject, VTCond_Base
import pymunk as pm
import numpy as np
import scipy.spatial as sps
import pdb
import re
import copy
import operator

__all__ = ['area_for_segment','area_for_poly','centroid_for_poly',
           'recenter_poly','object_complexity',
           'segs_to_poly','poly_validate', 'word_to_color', 'distance_to_object', 'calculate_derivatives','object_bounding_box',
           'calculate_derivatives_next_action', 'filter_collision_events', 'line_to_point_dist', 'follow_the_gradient',
           'strip_goal', 'update_object_properties',
           'verts_to_vec2d']

def verts_to_vec2d(vertex: Annotated[Tuple[float], 2]):
    return pm.Vec2d(vertex[0], vertex[1])

# Helper functions that are used to parse geometry
def area_for_poly(verts: Tuple[Tuple[float, float]]):
    area = 0
    #pmv = map(lambda v: pm.Vec2d(v), verts)
    pmv = [verts_to_vec2d(v) for v in list(verts)]
    for i in range(len(pmv)):
        v1 = pmv[i]
        v2 = pmv[(i+1) % len(pmv)]
        area += float(v1.cross(v2))
    return -area / 2.

def centroid_for_poly(verts: Tuple[Tuple[float, float]]):
    tsum = 0
    vsum = pm.Vec2d(0,0)
    pmv = [verts_to_vec2d(v) for v in list(verts)]
    #pmv = [*map(lambda v: pm.Vec2d(v), verts)]
    for i in range(len(pmv)):
        v1 = pmv[i]
        v2 = pmv[(i+1) % len(pmv)]
        cross = float(v1.cross(v2))
        tsum += cross
        vsum += (v1+v2) * cross
    return vsum * (1/(3*tsum))

def recenter_poly(verts: Tuple[Tuple[float, float]]):
    centroid = centroid_for_poly(verts)
    for i in range(len(verts)):
        verts[i] -= centroid
    return verts

def area_for_segment(a: Tuple[float, float],
                     b: Tuple[float, float],
                     r: float):
    va = verts_to_vec2d(a)
    vb = verts_to_vec2d(b)
    return r * (np.pi*r + 2*va.get_distance(vb))

def _isleft(spt, ept, testpt):
    seg1 = (ept[0]-spt[0], ept[1]-spt[1])
    seg2 = (testpt[0]-spt[0], testpt[1]-spt[1])
    cross = seg1[0]*seg2[1]-seg1[1]*seg2[0]
    return cross > 0

def segs_to_poly(seglist: Tuple[Tuple[float, float]],
                 r: float):
    vlist = [verts_to_vec2d(v) for v in seglist]
    #vlist = list(map(lambda p: pm.Vec2d(p), seglist))
    # Start by figuring out the initial edge (ensure ccw winding)
    iseg = vlist[1] - vlist[0]
    ipt = vlist[0]
    iang = iseg.angle
    if iang <= (-np.pi / 4.) and iang >= (-np.pi * 3. / 4.):
        # Going downwards
        prev1 = (ipt.x - r, ipt.y)
        prev2 = (ipt.x + r, ipt.y)
    elif iang >= (np.pi / 4.) and iang <= (np.pi * 3. / 4.):
        # Going upwards
        prev1 = (ipt.x + r, ipt.y)
        prev2 = (ipt.x - r, ipt.y)
    elif iang >= (-np.pi / 4.) and iang <= (np.pi / 4.):
        # Going rightwards
        prev1 = (ipt.x, ipt.y - r)
        prev2 = (ipt.x, ipt.y + r)
    else:
        # Going leftwards
        prev1 = (ipt.x, ipt.y + r)
        prev2 = (ipt.x, ipt.y - r)

    polylist = []
    for i in range(1, len(vlist)-1):
        pi = vlist[i]
        pim = vlist[i-1]
        pip = vlist[i+1]
        sm = pim - pi
        sp = pip - pi
        # Get the angle of intersetction between two lines
        angm = sm.angle
        angp = sp.angle
        angi = (angm - angp) % (2*np.pi)
        # Find the midpoint of this angle and turn it back into a unit vector
        angn = (angp + (angi / 2.)) % (2*np.pi)
        if angn < 0:
            angn += 2*np.pi
        unitn = pm.Vec2d(np.cos(angn), np.sin(angn))
        #unitn = pm.Vec2d.unit()
        #unitn.angle = angn
        xdiff = r if unitn.x >= 0 else -r
        ydiff = r if unitn.y >= 0 else -r
        next3 = (pi.x + xdiff, pi.y + ydiff)
        next4 = (pi.x - xdiff, pi.y - ydiff)
        # Ensure appropriate winding -- next3 should be on the left of next4
        if _isleft(prev2, next3, next4):
            tmp = next4
            next4 = next3
            next3 = tmp
        polylist.append((prev1, prev2, next3, next4))
        prev1 = next4
        prev2 = next3

    # Finish by figuring out the final edge
    fseg = vlist[-2] - vlist[-1]
    fpt = vlist[-1]
    fang = fseg.angle
    if fang <= (-np.pi / 4.) and fang >= (-np.pi * 3. / 4.):
        # Coming from downwards
        next3 = (fpt.x - r, fpt.y)
        next4 = (fpt.x + r, fpt.y)
    elif fang >= (np.pi / 4.) and fang <= (np.pi * 3. / 4.):
        # Coming from upwards
        next3 = (fpt.x + r, fpt.y)
        next4 = (fpt.x - r, fpt.y)
    elif fang >= (-np.pi / 4.) and fang <= (np.pi / 4.):
        # Coming from rightwards
        next3 = (fpt.x, fpt.y - r)
        next4 = (fpt.x, fpt.y + r)
    else:
        # Coming from leftwards
        next3 = (fpt.x, fpt.y + r)
        next4 = (fpt.x, fpt.y - r)
    polylist.append((prev1, prev2, next3, next4))
    return polylist

def _vcross2(x1,y1,x2,y2):
    return x1*y2 - y1*x2

def poly_validate(verts: Tuple[Tuple[float, float]]):
    for i in range(len(verts)):
        ax,ay = verts[i]
        bx,by = verts[(i+1)%len(verts)]
        cx,cy = verts[(i+2)%len(verts)]
        if _vcross2(bx-ax, by-ay, cx-by, cy-by) > 0:
            return False
    return True

def object_bounding_box(object: VTObject):
    bb = [0,0]
    if object.type == 'Ball':
        bb[0] = [object.position[0] - object.radius, object.position[1] - object.radius]
        bb[1] = [object.position[0] + object.radius, object.position[1] + object.radius]
    elif object.type == 'Poly' or object.type == 'Container':
        vert_x = [vert[0] for vert in object.vertices]
        vert_y = [vert[1] for vert in object.vertices]
        bb[0] = [min(vert_x), min(vert_y)]
        bb[1] = [max(vert_x), max(vert_y)]
    elif object.type == 'Compound':
        vert_x = [vert[0] for o in object.polys for vert in o ]
        vert_y = [vert[1] for o in object.polys for vert in o ]
        bb[0] = [min(vert_x), min(vert_y)]
        bb[1] = [max(vert_x), max(vert_y)]
    else:
        bb = None
    return bb

def object_complexity(object: VTObject):
    #this assumes the complexity is measured as the distance to the convex hull
    verts = [obj[i] for obj in object for i in range(0, len(obj))]

    hull = sps.ConvexHull(verts)
    hull_verts = np.array(verts)[hull.vertices].tolist()
    complexity = (np.abs(area_for_poly(hull_verts))-area_for_poly(verts))/np.abs(area_for_poly(hull_verts))
    return complexity

def word_to_color(colorname: str):
    if colorname is None:
        return None
    try:
        cvec = [int(c) for c in colorname]
        return cvec
    except:
        if colorname == 0:
            return (0, 0, 0, 255)
        c = colorname.lower()
        if c == 'blue':
            return (0,0,255,255)
        elif c == 'red':
            return (255,0,0,255)
        elif c == 'green':
            return (0,255,0,255)
        elif c == 'black':
            return (0,0,0,255)
        elif c == 'white':
            return (255,255,255,255)
        elif c == 'grey' or c == 'gray':
            return (127,127,127,255)
        elif c == 'lightgrey':
            return (191,191,191,255)
        elif c == 'none':
            return (0, 0, 0, 0)
        else:
            raise Exception('Color name not known: ' + c)

def euclidDist(p1: Tuple[float, float],
               p2: Tuple[float, float]):
    return np.linalg.norm(np.array(p1) - np.array(p2))

def line_to_point_dist(l1: Tuple[float, float],
                       l2: Tuple[float, float],
                       p: Tuple[float, float]):
    x0, y0 = p
    x1, y1 = l1
    x2, y2 = l2
    #pdb.set_trace()

    p_np = np.array([x0, y0])
    l1_np = np.array([x1, y1])
    l2_np = np.array([x2, y2])
    #pdb.set_trace()
    t_hat = np.dot(p_np - l1_np, l2_np - l1_np)/(np.dot((l2_np - l1_np).T,(l2_np - l1_np)))
    t_star = min(max(t_hat, 0), 1)

    s_t = l1_np + t_star*(l2_np - l1_np)
    distance = np.linalg.norm(s_t - p_np)
    #distance = np.abs((y2 - y1)*x0 - (x2 - x1)*y0 + x2*y1 - y2*x1)/np.sqrt(
    #    (y2-y1)**2 + (x2-x1)**2)
    return distance

def distance_to_object(object: VTObject,
                       point: Tuple[float, float]):
    if object.type != 'Container':
        return euclidDist(object.position, point)
    else:
        wall_list = object.seglist
        wall_opening = wall_list[0]
        wall_closing = wall_list[-1]

        distance = line_to_point_dist(wall_opening, wall_closing, point)
        return distance


def calculate_derivatives(func, f_xy, x, y, h, k,tp,hessian=False, return_vals=False):

    def get_movement(pos_x, step_x, pos_y, step_y, reduce_factor=2):
        while tp.checkPlacementCollide('obj1', [pos_x+step_x,pos_y+step_y]):
            step_x = step_x/reduce_factor
            step_y = step_y/reduce_factor
        return pos_x+step_x, pos_y+step_y, step_x, step_y

    xph, _, spx, _ = get_movement(x, h, y, 0)
    xmh, _, smx, _ = get_movement(x, -h, y, 0)
    _, ypk, _, spy = get_movement(x, 0, y, k)
    _, ymk, _, smy = get_movement(x, 0, y, -k)
    h = (spx-smx)/2.
    k = (spy-smy)/2.

    f_xph = func(xph, y)
    f_xmh = func(xmh, y)

    f_ypk = func(x, ypk)
    f_ymk = func(x, ymk)
    f_x = [(f_xph - f_xy)/spx, (f_xmh - f_xy)/smx]
    f_y = [(f_ypk - f_xy)/spy, (f_ymk - f_xy)/smy]

    if hessian:
        xph_, ypk_, spx_, spy_ = get_movement(x, h, y, k)
        xmh_, ymk_, smx_, smy_ = get_movement(x, -h, y, -k)
        f_xph_ypk = func(xph_, ypk_)
        f_xmh_ymk = func(xmh_, ymk_)
        h = (spx_ - smx_)/2.
        k = (spy_ - smy_)/2.

        f_xx = (f_xph - 2*f_xy + f_xmh)/(h*h)
        f_yy = (f_ypk - 2*f_xy + f_ymk)/(k*k)
        f_xy_prime = (f_xph_ypk - f_xph - f_ypk + 2*f_xy - f_xmh - f_ymk + f_xmh_ymk)/(2*h*k)
        if return_vals:
            return sum(f_x)/2., sum(f_y)/2., f_xx, f_yy, f_xy_prime, h, k, f_xph, f_xmh, f_ypk, f_ymk
        else:
            return sum(f_x)/2., sum(f_y)/2., f_xx, f_yy, f_xy_prime, h, k
    if return_vals:
        return sum(f_x)/2., sum(f_y)/2., 0, 0, 0, h, k, f_xph, f_xmh, f_ypk, f_ymk
    else:
        return sum(f_x)/2., sum(f_y)/2., 0, 0, 0, h, k

def follow_the_gradient(func, centered_obj, action, h=1, k=1, num_samples=1, num_steps=5, step_size=5, return_vals=False):

    x = action.position[0]
    y = action.position[1]
    tp = action.tp
    next_step = [x,y]
    for step in range(num_steps):
        deriv_samps = np.zeros((1,5))
        vals = np.zeros((1, 4))
        #run the derivatives calculation for a given number of samples

        for i in range(num_samples):
            derivs = calculate_derivatives(func, centered_obj, next_step[0], next_step[1], h, k, tp, True, return_vals)
            if len(derivs) > 7:
                vals = np.vstack((vals, derivs[7:]))

            deriv_samps = np.vstack((deriv_samps, derivs[:5]))

        final_derivs = np.mean(deriv_samps[1:,:],0)

        hessian = np.zeros((2,2))
        hessian[0,0] = final_derivs[2]
        hessian[0,1] = hessian[1,0] = final_derivs[3]
        hessian[1,1] = final_derivs[4]

        sym_hessian = 0.5*(hessian + hessian.T)
        inverse_hess = np.linalg.inv(sym_hessian)
        jacobian = np.zeros((1,2))

        jacobian[0,0] = final_derivs[0]
        jacobian[0,1] = final_derivs[1]
        next_step = [next_step[0],next_step[1]] - np.dot(jacobian, inverse_hess)[0]#step_size*np.array([derivs[-2],derivs[-1]])*jacobian[0]
        centered_obj = func(next_step[0], next_step[1])
    if return_vals:
        return next_step, centered_obj, [x,y] - next_step, vals[1:,:]
    return next_step, centered_obj, [x,y] - next_step


def calculate_derivatives_next_action(func, centered_obj, action, h=1, k=1, num_samples=1):
    x = action[0]
    y = action[1]
    deriv_samps = np.zeros((1,5))
    #run the derivatives calculation for a given number of samples

    for i in range(num_samples):
        deriv_samps = np.vstack((deriv_samps, calculate_derivatives(func, centered_obj, x, y, h, k, False)))

    final_derivs = np.mean(deriv_samps[1:,:],0)

    hessian = np.zeros((2,2))
    jacobian = np.zeros((1,2))

    jacobian[0,0] = final_derivs[0]
    jacobian[0,1] = final_derivs[1]
    #next_step = [x,y] - np.transpose(np.dot(hessian_inv,np.transpose(jacobian)))[0]
    return [x,y], jacobian[0]#np.transpose(np.dot(hessian_inv,np.transpose(jacobian)))[0]

def order_contacts(fc):
    fc = sorted(fc, key=operator.itemgetter(2))
    return fc

def filter_collision_events(eventlist, slop_time = .2):
    begin_list = {}
    last_list = {}
    col_list = {}
    col_list_beg = {}
    output_events = []

    for o1,o2,tp,tm,ci in eventlist:
        if o2 < o1:
            tmp = o2
            o2 = o1
            o1 = tmp
            # Also need to swap the normals
            new_cins = []
            for n in ci[0]:
                new_cins.append({'x': -n['x'], 'y': -n['y']})
            ci[0] = new_cins

        comb = re.sub('__', '_', o1+"_"+o2).strip('_') # Filtering for objects that start with _
        if tp == 'begin':
            # We have already seen them disconnect
            if comb in last_list.keys():
                # Long break since last time they were connected
                if tm - last_list[comb] > slop_time:
                    try:
                        output_events.append([o1,o2,begin_list[comb],last_list[comb], col_list[comb]])
                    except:
                        output_events.append([o1, o2, 0.1, last_list[comb], col_list[comb]])

                    del last_list[comb]
                    del col_list[comb]
                    begin_list[comb] = tm
                    col_list_beg[comb] = ci
                # Short break since connection
                else:
                    del last_list[comb]
                    del col_list[comb]
            # We have not yet seen them disconnect -- so they have never been together
            else:
                begin_list[comb] = tm
                col_list_beg[comb] = ci
        elif tp == 'end':
            last_list[comb] = tm
            col_list[comb] = ci

    # Clear out disconnects that never reconnect
    for comb, tm in last_list.items():
        o1, o2 = comb.split('_')
        try:
            output_events.append([o1,o2,begin_list[comb], last_list[comb], col_list[comb]])
            del begin_list[comb]
            del col_list_beg[comb]
        except:
            # Sometimes beginning touch doesn't show up on Kelsey's computer...
            output_events.append([o1,o2,0.1, last_list[comb], col_list[comb]])


    # Add in the items still in contact
    for comb, tm in begin_list.items():
        o1, o2 = comb.split('_')
        output_events.append([o1,o2,tm,None,col_list_beg[comb]])

    return order_contacts(output_events)

def strip_goal(worlddict):
    wd = copy.deepcopy(worlddict)
    wd['objects']['FAKE_GOAL_7621895'] = {
        "type": "Goal",
        "color": "green",
        "density": 0,
        "vertices": [[-10, -10], [-10, -5], [-5, -5], [-5, -10]]
    }
    wd['objects']['FAKE_BALL_213232'] = {
        "type": "Ball",
        "color": "red",
        "density": 1,
        "position": [-100, -10],
        "radius": 2
    }
    wd['gcond'] = {
        "type": "SpecificInGoal",
        "goal": 'FAKE_GOAL_7621895',
        "obj": 'FAKE_BALL_213232',
        "duration": 2000
    }
    return wd

def update_object_properties(worlddict: Dict,
                             newobjdict: Dict):
    wd = copy.deepcopy(worlddict)
    approp_params = ['density', 'elasticity', 'friction']
    for obj, vals in newobjdict.items():
        if obj not in wd['objects']:
            print("Error: " + obj + " not found")
        else:
            o = wd['objects'][obj]
        for pnm, pval in vals.items():
            if pnm not in approp_params:
                print("Error: cannot set " + pnm)
            else:
                o[pnm] = pval
    return wd
