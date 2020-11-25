from dxtbx.model.crystal import Crystal
from cctbx import uctbx
from scitbx.matrix import sqr, rec
from scipy.spatial.transform import Rotation
from simtbx.diffBragg.nanoBragg_crystal import nanoBragg_crystal
from simtbx.diffBragg.sim_data import SimData
from simtbx.diffBragg import utils


ucell = (85.2, 96, 124, 90, 105, 90)
symbol = "P121"

# generate a random raotation
rotation = Rotation.random(num=1, random_state=1107)[0]
Q = rec(rotation.as_quat(), n=(4, 1))
rot_ang, rot_axis = Q.unit_quaternion_as_axis_and_angle()

# make the ground truth crystal:
a_real, b_real, c_real = sqr(uctbx.unit_cell(ucell).orthogonalization_matrix()).transpose().as_list_of_lists()
C = Crystal(a_real, b_real, c_real, symbol)
C.rotate_around_origin(rot_axis, rot_ang)

# Setup the simulation and create a realistic image
# with background and noise
# <><><><><><><><><><><><><><><><><><><><><><><><><>
nbcryst = nanoBragg_crystal()
nbcryst.dxtbx_crystal = C   # simulate ground truth
nbcryst.thick_mm = 0.1
nbcryst.Ncells_abc = 19, 19, 19

print ("Ground truth ncells abc=%f" % (nbcryst.Ncells_abc[0]))

# generate the ground truth image
SIM = SimData()
SIM.detector = SimData.simple_detector(200, 0.1, (1024, 1024))
SIM.crystal = nbcryst
SIM.instantiate_diffBragg(oversample=0)
SIM.D.progress_meter = False
SIM.water_path_mm = 0.005
SIM.air_path_mm = 0.1
SIM.add_air = True
SIM.add_Water = True
SIM.include_noise = True
SIM.D.add_diffBragg_spots()
spots = SIM.D.raw_pixels.as_numpy_array()
SIM._add_background()
SIM._add_noise()
# This is the ground truth image:
img = SIM.D.raw_pixels.as_numpy_array()
SIM.D.raw_pixels *= 0

# perturb
Ncells_abc_2 = 26, 26, 26

from dxtbx.model import Experiment
from simtbx.nanoBragg import make_imageset
from cctbx_project.simtbx.diffBragg.phil import phil_scope
from simtbx.diffBragg import refine_launcher
E = Experiment()
E.detector = SIM.detector
E.beam = SIM.D.beam
E.crystal = C
E.imageset = make_imageset([img], E.beam, E.detector)

refls = utils.refls_from_sims([spots], E.detector, E.beam, thresh=20)

P = phil_scope.extract()
P.roi.shoebox_size = 20
P.roi.reject_edge_reflections = False
P.refiner.refine_ncells = [1]
P.refiner.max_calls = [1000]
P.refiner.tradeps = 1e-10
# NOTE RUC.gtol = .9
# NOTE RUC.trad_conv = True  #False
# NOTE RUC.drop_conv_max_eps = 1e-9
P.refiner.curvatures = False
P.refiner.use_curvatures_threshold = 0
P.refiner.poissononly = False
P.refiner.verbose = True
P.refiner.big_dump = False
P.refiner.sigma_r = SIM.D.readout_noise_adu
P.refiner.adu_per_photon = SIM.D.quantum_gain
P.simulator.crystal.ncells_abc = Ncells_abc_2
P.simulator.init_scale = SIM.D.spot_scale
P.simulator.beam.size_mm = SIM.beam.size_mm
P.refiner.ncells_mask = "111"

# assert RUC.all_ang_off[0] < 0.005
RUC = refine_launcher.local_refiner_from_parameters(refls, E, P, miller_data=SIM.crystal.miller_array)
assert round(RUC.D.get_value(9)) == 19
print("OK")