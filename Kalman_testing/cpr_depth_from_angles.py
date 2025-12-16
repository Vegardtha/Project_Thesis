"""
CPR depth from two IMU angles using a full-cosine path (period L).
Usage (as a module):
    from cpr_depth_from_angles import depth_from_two_angles
    res = depth_from_two_angles(theta1_deg=-34, theta2_deg=32.5, s_mm=107, L_mm=240)

If used as a script, you can quickly edit the values at the bottom and run:
    python cpr_depth_from_two_angles.py
"""

import math
from dataclasses import dataclass
from typing import Optional

@dataclass
class DepthResult:
    ok: bool
    D_mm: float = float('nan')      # peak depth (amplitude)
    x1_mm: float = float('nan')     # IMU1 position (wrapped to [0, L))
    x2_mm: float = float('nan')     # IMU2 position (unwrapped = x1 + s)
    y1_mm: float = float('nan')     # depth at IMU1 (negative = down)
    y2_mm: float = float('nan')     # depth at IMU2
    ymin_mm: float = float('nan')   # deepest point on [x1, x1+s]
    xmin_mm: float = float('nan')   # where that minimum occurs (unwrapped)
    message: Optional[str] = None

def _wrap_pos(x: float, m: float) -> float:
    r = x % m
    return r if r >= 0 else r + m

def depth_from_two_angles(theta1_deg: float, theta2_deg: float,
                          s_mm: float, L_mm: float = 240.0,
                          segment_samples: int = 400,
                          slope_tol: float = 1e-3) -> DepthResult:
    """
    Solve the full-cosine model:
      y(x) = -D/2 * (1 - cos(2π x / L))
      y'(x) = -(Dπ/L) * sin(2π x / L)
    Inputs:
      theta1_deg: angle at IMU1 (degrees)
      theta2_deg: angle at IMU2 (degrees)
      s_mm: separation between IMUs along x (mm)
      L_mm: period of the cosine (mm), default 240 mm
    Returns:
      DepthResult with:
        D_mm: amplitude (peak depth)
        y1_mm, y2_mm: depths at the two IMU positions
        ymin_mm: max depth (most negative y) along the segment [x1, x1+s]
    """
    R = DepthResult(ok=False)

    if L_mm <= 0 or s_mm <= 0:
        R.message = "L_mm and s_mm must be positive."
        return R

    rad = math.pi / 180.0
    m1 = math.tan(theta1_deg * rad)
    m2 = math.tan(theta2_deg * rad)

    if not math.isfinite(m1) or not math.isfinite(m2):
        R.message = "Angles produce non-finite tangent."
        return R
    if abs(m1) < 1e-9:
        R.message = "First angle too close to 0°, cannot solve reliably."
        return R

    # --- Updated, more stable phase/depth solve (atan2 + best-conditioned family) ---
    phi = 2.0 * math.pi * (s_mm / L_mm)

    # ---------- choose the better-anchored sensor for phase solve ----------
    # If |m1| is tiny but |m2| isn't, solve phase relative to sensor 2, then
    # convert back so 'a' always corresponds to sensor 1 at x1.
    def solve_a_from_ratio(mA, mB, phiAB):
        # ratio r = mB/mA, phase a_A satisfies tan(a_A) = -sinφ / (cosφ - r)
        r = mB / mA
        numer = -math.sin(phiAB)
        denom =  math.cos(phiAB) - r
        return math.atan2(numer, denom)  # a_A

    swap_phase = False
    if abs(m1) < 1e-3 and abs(m2) >= 1e-3:
        # anchor on sensor 2, then shift phase back to sensor 1
        a2 = solve_a_from_ratio(m2, m1, -phi)  # a2 for sensor2
        a0 = a2 - phi                          # a for sensor1
        swap_phase = True  # just for debugging/awareness; no other effect
    else:
        a0 = solve_a_from_ratio(m1, m2, +phi)

    # ---------- helpers ----------
    def y(x_mm, D):
        return -0.5 * D * (1.0 - math.cos(2.0 * math.pi * (x_mm / L_mm)))
    def yp(x_mm, D):
        return -(D * math.pi / L_mm) * math.sin(2.0 * math.pi * (x_mm / L_mm))

    best = None
    best_cond = -1.0

    for k in range(-3, 4):
        a = a0 + k * math.pi
        s1 = math.sin(a)
        s2 = math.sin(a + phi)

        # both-sides conditioning: require both sensors to be usable
        cond = min(abs(s1), abs(s2))
        if cond < 1e-2:
            continue

        # depth from each slope, then weighted blend
        D1 = -(L_mm / math.pi) * (m1 / s1)
        D2 = -(L_mm / math.pi) * (m2 / s2)

        if not (math.isfinite(D1) and math.isfinite(D2)):
            continue

        # reject non-physical (negative) depths
        if D1 <= 0 and D2 <= 0:
            continue

        # simple consistency check between D1 and D2
        if D1 > 0 and D2 > 0:
            if abs(D1 - D2) > 0.5 * (D1 + D2):  # > ~50% disagreement
                # keep going but downweight the outlier via weights below
                pass

        w1 = abs(s1)
        w2 = abs(s2)
        D = (w1 * max(D1, 0.0) + w2 * max(D2, 0.0)) / (w1 + w2)

        if not math.isfinite(D) or D <= 0:
            continue

        x1 = _wrap_pos((a * L_mm) / (2.0 * math.pi), L_mm)
        x2 = x1 + s_mm

        # verify both slopes against the model
        if abs(yp(x1, D) - m1) > slope_tol:
            continue
        if abs(yp(_wrap_pos(x2, L_mm), D) - m2) > slope_tol:
            continue

        # values at sensors
        y1 = y(x1, D)
        y2 = y(x2, D)

        # analytic deepest point on [x1, x2]: check endpoints + x = n L/2
        xmin_candidates = [x1, x2]
        n_start = math.floor((2.0 * x1 / L_mm) - 1)
        n_end   = math.ceil ((2.0 * x2 / L_mm) + 1)
        for n in range(n_start, n_end + 1):
            xx = (n * L_mm) / 2.0
            if x1 <= xx <= x2:
                xmin_candidates.append(xx)
        ymin = None
        xmin = None
        for xx in xmin_candidates:
            yy = y(xx, D)
            if ymin is None or yy < ymin:
                ymin, xmin = yy, xx

        # pick the candidate that is best for BOTH sensors
        if cond > best_cond:
            best = (D, x1, x2, y1, y2, ymin, xmin)
            best_cond = cond

    if best is not None:
        D, x1, x2, y1, y2, ymin, xmin = best
        R.ok = True
        R.D_mm = D
        R.x1_mm = x1
        R.x2_mm = x2
        R.y1_mm = y1
        R.y2_mm = y2
        R.ymin_mm = ymin
        R.xmin_mm = xmin
        R.message = "Solved."
        return R


    R.message = "No consistent solution found for given angles/separation/period."
    return R


if __name__ == "__main__":
    # Example inputs
    theta1_deg =  25.1
    theta2_deg =  1.0
    s_mm       = 103.0
    L_mm       = 240.0

    res = depth_from_two_angles(theta1_deg, theta2_deg, s_mm, L_mm, segment_samples=800)
    print("OK:", res.ok, "-", res.message)
    if res.ok:
        print(f"D (peak depth) [mm] = {res.D_mm:.3f}")
        print(f"x1 [mm] = {res.x1_mm:.3f}")
        print(f"x2 [mm] = {res.x2_mm:.3f}")
        print(f"y1 [mm] = {res.y1_mm:.3f}")
        print(f"y2 [mm] = {res.y2_mm:.3f}")
        print(f"Max depth on segment [mm] = {res.ymin_mm:.3f} at x = {res.xmin_mm:.3f} mm")
    else:
        print("No solution with these inputs. Try changing L_mm, s_mm or the angles.")
