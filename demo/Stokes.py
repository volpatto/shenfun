r"""Solve Stokes equations using a coupled formulation

The Stokes equations are in strong form

.. math::

    -\nabla^2 u - \nabla p &= f \\
    \nabla \cdot u &= h \\
    u(x, y=\pm 1) &= 0 \\
    u(x=2\pi, y) &= u(x=0, y) \\
    p(x=2\pi, y) &= p(x=0, y)

where :math:`f` and :math:`g` are given functions of space.
In addition we require :math:`\int p dx = 0`, which is achieved by
fixing the coefficient :math:`\hat{p}_{0, 0} = 0`.

We use a tensorproductspace with Fourier expansions in the x-direction and
a composite Chebyshev or Legendre basis in the y-direction for ``u`` and
a regular (no boundary conditions) Chebyshev or Legendre basis for ``p``.

To eliminate a nullspace we use a P_N basis for the velocity and a P_{N-2}
basis for the pressure.
"""
import os
import sys
import numpy as np
from mpi4py import MPI
from sympy import symbols, sin, lambdify
from shenfun import *

comm = MPI.COMM_WORLD
x, y = symbols("x,y")

# Some right hand side (manufactured solution)
uex = sin(2*y)*(1-y**2)
uey = sin(2*x)*(1-y**2)
pe = -0.1*sin(2*x)
fx = -uex.diff(x, 2) - uex.diff(y, 2) - pe.diff(x, 1)
fy = -uey.diff(x, 2) - uey.diff(y, 2) - pe.diff(y, 1)
h = uex.diff(x, 1) + uey.diff(y, 1)

# Lambdify for faster evaluation
ulx = lambdify((x, y), uex, 'numpy')
uly = lambdify((x, y), uey, 'numpy')
flx = lambdify((x, y), fx, 'numpy')
fly = lambdify((x, y), fy, 'numpy')
hl = lambdify((x, y), h, 'numpy')
pl = lambdify((x, y), pe, 'numpy')

N = (100, 100)
family = sys.argv[-1] if len(sys.argv) == 2 else 'Legendre'
K0 = Basis(N[0], 'Fourier', dtype='d', domain=(0, 2*np.pi))
SD = Basis(N[1], family, bc=(0, 0))
ST = Basis(N[1], family)

# To get a P_N x P_{N-2} space, just pick the first N-1 items of the pressure basis
# Note that this effectively sets the two highest pressure frequencies to zero, but
# still the basis uses the same quadrature points as the Dirichlet basis, which is
# required for the inner products.
ST.slice = lambda: slice(0, ST.N-2)

TD = TensorProductSpace(comm, (K0, SD), axes=(1, 0))
TT = TensorProductSpace(comm, (K0, ST), axes=(1, 0))
VT = VectorTensorProductSpace(TD)
Q = MixedTensorProductSpace([VT, TT])
X = TD.local_mesh(True)

up = TrialFunction(Q)
vq = TestFunction(Q)

u, p = up
v, q = vq

# Assemble blocks of complete matrix
if family.lower() == 'chebyshev':
    A00 = inner(v, -div(grad(u)))
    A01 = inner(v, -grad(p))
else:
    A00 = inner(grad(v), grad(u))
    A01 = inner(div(v), p)
A10 = inner(q, div(u))

# Create block matrix
M = BlockMatrix(A00+A01+A10)

# Get f and h on quad points
fh = Array(Q)
fh[0] = flx(*X)
fh[1] = fly(*X)
fh[2] = hl(*X)

fh_hat = Function(Q)
fh_hat[:2] = inner(v, fh[:2], output_array=fh_hat[:2])
fh_hat[2] = inner(q, fh[2], output_array=fh_hat[2])

# Solve problem using integral constraint on pressure
up_hat = M.solve(fh_hat, integral_constraint=(2, 0))
up = up_hat.backward()

# Exact solution
ux = ulx(*X)
uy = uly(*X)
pe = pl(*X)

error = [comm.reduce(np.linalg.norm(ux-up[0])),
         comm.reduce(np.linalg.norm(uy-up[1])),
         comm.reduce(np.linalg.norm(pe-up[2]))]

if comm.Get_rank() == 0:
    print('Error    u          v          p')
    print('     %2.4e %2.4e %2.4e' %(error[0], error[1], error[2]))
    assert np.all(abs(np.array(error)) < 1e-8), error

if 'pytest' not in os.environ:
    import matplotlib.pyplot as plt
    plt.figure()
    plt.contourf(X[0], X[1], up[2], 100)
    plt.figure()
    plt.quiver(X[0], X[1], up[0], up[1])
    plt.figure()
    plt.spy(M.diags((0, 0)).toarray()) # The matrix for Fourier given wavenumber
    plt.figure()
    plt.contourf(X[0], X[1], up[0], 100)
    #plt.show()
