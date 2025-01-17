from __future__ import absolute_import, division, print_function
from cctbx import adptbx, crystal, miller, sgtbx, uctbx, xray
from cctbx.array_family import flex
import iotbx.cif
from iotbx.cif import model
from libtbx.utils import Sorry
from libtbx.containers import OrderedDict, OrderedSet
import warnings
from six import string_types
from six.moves import range
import six, re
from six.moves import zip

# Refer to https://www.iucr.org/__data/iucr/cifdic_html/2/cif_mm.dic/index.html for definitons
# of elements and columns in a CIF file

class CifBuilderError(Sorry):
  __module__ = Exception.__module__

def CifBuilderWarning(message):
  warnings.showwarning(message, UserWarning, 'CifBuilderWarning', '')

class cif_model_builder(object):

  def __init__(self, cif_object=None):
    self._model = cif_object
    if self._model is None:
      self._model = model.cif()
    self._current_block = None
    self._current_save = None

  def add_data_block(self, data_block_heading):
    self._current_block = model.block()
    if data_block_heading.lower() == 'global_':
      block_name = data_block_heading
    else:
      block_name = data_block_heading[data_block_heading.find('_')+1:]
    self._model[block_name] = self._current_block

  def add_loop(self, header, columns):
    if self._current_save is not None:
      block = self._current_save
    else:
      block = self._current_block
    loop = model.loop()
    assert len(header) == len(columns)
    n_columns = len(columns)
    for i in range(n_columns):
      loop[header[i]] = columns[i]
    block.add_loop(loop)

  def add_data_item(self, key, value):
    if self._current_save is not None:
      self._current_save[key] = value
    elif self._current_block is not None:
      self._current_block[key] = value
    else: # support for global_ blocks in non-strict mode
      pass

  def start_save_frame(self, save_frame_heading):
    assert self._current_save is None
    self._current_save = model.save()
    save_name = save_frame_heading[save_frame_heading.find('_')+1:]
    self._current_block[save_name] = self._current_save

  def end_save_frame(self):
    self._current_save = None

  def model(self):
    return self._model


class builder_base(object):

  __equivalents__ = {
    '_space_group_symop_operation_xyz': ('_symmetry_equiv_pos_as_xyz',
                                         '_space_group_symop.operation_xyz',
                                         '_symmetry_equiv.pos_as_xyz'),
    '_space_group_symop_id': ('_symmetry_equiv_pos_site_id',
                              '_space_group_symop.id',
                              '_symmetry_equiv.id'),
    '_space_group_name_Hall': ('_symmetry_space_group_name_Hall',
                               '_space_group.name_Hall',
                               '_symmetry.space_group_name_Hall'),
    '_space_group_name_H-M_alt': ('_symmetry_space_group_name_H-M',
                                  '_space_group.name_H-M_alt',
                                  '_symmetry.space_group_name_H-M'),
    '_space_group_IT_number': ('_symmetry_Int_Tables_number',
                                 '_symmetry.Int_Tables_number'
                                 '_space_group.IT_number'),
    '_cell_length_a': ('_cell.length_a',),
    '_cell_length_b': ('_cell.length_b',),
    '_cell_length_c': ('_cell.length_c',),
    '_cell_angle_alpha': ('_cell.angle_alpha',),
    '_cell_angle_beta': ('_cell.angle_beta',),
    '_cell_angle_gamma': ('_cell.angle_gamma',),
    '_cell_volume': ('_cell.volume',),
    '_refln_index_h': ('_refln.index_h',),
    '_refln_index_k': ('_refln.index_k',),
    '_refln_index_l': ('_refln.index_l',),
  }

  def get_cif_item(self, key, default=None):
    value = self.cif_block.get(key)
    if value is not None: return value
    for equiv in self.__equivalents__.get(key, []):
      value = self.cif_block.get(equiv)
      if value is not None: return value
    return default


class crystal_symmetry_builder(builder_base):

  def __init__(self, cif_block, strict=False):
    # The order of priority for determining space group is:
    #   sym_ops, hall symbol, H-M symbol, space group number
    self.cif_block = cif_block
    sym_ops = self.get_cif_item('_space_group_symop_operation_xyz')
    sym_op_ids = self.get_cif_item('_space_group_symop_id')
    space_group = None
    if sym_ops is not None:
      if isinstance(sym_ops, string_types):
        sym_ops = flex.std_string([sym_ops])
      if sym_op_ids is not None:
        if isinstance(sym_op_ids, string_types):
          sym_op_ids = flex.std_string([sym_op_ids])
        assert len(sym_op_ids) == len(sym_ops)
      self.sym_ops = {}
      space_group = sgtbx.space_group()
      if isinstance(sym_ops, string_types): sym_ops = [sym_ops]
      for i, op in enumerate(sym_ops):
        try:
          s = sgtbx.rt_mx(op)
        except RuntimeError as e:
          str_e = str(e)
          if "Parse error: " in str_e:
            raise CifBuilderError("Error interpreting symmetry operator: %s" %(
              str_e.split("Parse error: ")[-1]))
          else:
            raise
        if sym_op_ids is None:
          sym_op_id = i+1
        else:
          try:
            sym_op_id = int(sym_op_ids[i])
          except ValueError as e:
            raise CifBuilderError("Error interpreting symmetry operator id: %s" %(
              str(e)))
        self.sym_ops[sym_op_id] = s
        space_group.expand_smx(s)
    else:
      hall_symbol = self.get_cif_item('_space_group_name_Hall')
      hm_symbol = self.get_cif_item('_space_group_name_H-M_alt')
      sg_number = self.get_cif_item('_space_group_IT_number')
      if space_group is None and hall_symbol not in (None, '?'):
        try: space_group = sgtbx.space_group(hall_symbol)
        except Exception: pass
      if space_group is None and hm_symbol not in (None, '?'):
        try: space_group = sgtbx.space_group_info(symbol=hm_symbol).group()
        except Exception: pass
      if space_group is not None and sg_number not in (None, '?'):
        try: space_group = sgtbx.space_group_info(number=sg_number).group()
        except Exception: pass
      if (space_group is None and strict):
        raise CifBuilderError(
          "No symmetry instructions could be extracted from the cif block")
    items = [self.get_cif_item("_cell_length_"+s) for s in "abc"]
    for i, item in enumerate(items):
      if isinstance(item, flex.std_string):
        raise CifBuilderError(
          "Data item _cell_length_%s cannot be declared in a looped list"
          %("abc"[i]))
    for s in ["alpha", "beta", "gamma"]:
      item = self.get_cif_item("_cell_angle_"+s)
      if isinstance(item, flex.std_string):
        raise CifBuilderError(
          "Data item _cell_angle_%s cannot be declared in a looped list" %s)
      if (item == "?"):
        item = "90" # enumeration default for angles is 90 degrees
      items.append(item)
    ic = items.count(None)
    if (ic == 6):
      if (strict):
        raise CifBuilderError(
          "Unit cell parameters not found in the cif file")
      unit_cell = None
    elif (ic == 0):
      try:
        vals = [float_from_string(s) for s in items]
      except ValueError:
        raise CifBuilderError("Invalid unit cell parameters are given")
      try:
        unit_cell = uctbx.unit_cell(vals)
      except RuntimeError as e:
        if "cctbx Error: Unit cell" in str(e):
          raise CifBuilderError(e)
        else:
          raise
    elif (space_group is not None):
      unit_cell = uctbx.infer_unit_cell_from_symmetry(
        [float_from_string(s) for s in items if s is not None], space_group)
    else:
      raise CifBuilderError(
        "Not all unit cell parameters are given in the cif file")
    if unit_cell is not None and space_group is not None:
      if not space_group.is_compatible_unit_cell(unit_cell):
        # try primitive setting
        space_group_input = space_group
        space_group = space_group.info().primitive_setting().group()
        if not space_group.is_compatible_unit_cell(unit_cell):
          raise CifBuilderError(
            "Space group is incompatible with unit cell parameters:\n" + \
            "  Space group: %s\n" %space_group_input.info() + \
            "  Unit cell: %s" %unit_cell)
    self.crystal_symmetry = crystal.symmetry(unit_cell=unit_cell,
                                             space_group=space_group)

class crystal_structure_builder(crystal_symmetry_builder):

  def __init__(self, cif_block):
    # XXX To do: interpret _atom_site_refinement_flags
    crystal_symmetry_builder.__init__(self, cif_block, strict=True)
    atom_sites_frac = [
      as_double_or_none_if_all_question_marks(
        _, column_name='_atom_site_fract_%s' %axis)
      for _, axis in [(cif_block.get('_atom_site_fract_%s' %axis), axis)
                      for axis in ('x','y','z')]]
    if atom_sites_frac.count(None) == 3:
      atom_sites_cart = [as_double_or_none_if_all_question_marks(
        _, column_name='_atom_site_Cartn_%s' %axis)
                         for _ in [cif_block.get('_atom_site_Cartn_%s' %axis)
                                   for axis in ('x','y','z')]]
      if atom_sites_cart.count(None) != 0:
        raise CifBuilderError("No atomic coordinates could be found")
      atom_sites_cart = flex.vec3_double(*atom_sites_cart)
      # XXX do we need to take account of _atom_sites_Cartn_tran_matrix_ ?
      atom_sites_frac = self.crystal_symmetry.unit_cell().fractionalize(
        atom_sites_cart)
    else:
      if atom_sites_frac.count(None) != 0:
        raise CifBuilderError("No atomic coordinates could be found")
      atom_sites_frac = flex.vec3_double(*atom_sites_frac)
    labels = cif_block.get('_atom_site_label')
    type_symbol = cif_block.get('_atom_site_type_symbol')
    if type_symbol:
      type_symbol = flex.std_string(
        s.replace('0+', '').replace('0-', '') for s in type_symbol)
    U_iso_or_equiv = flex_double_else_none(
      cif_block.get('_atom_site_U_iso_or_equiv',
      cif_block.get('_atom_site_U_equiv_geom_mean')))
    if U_iso_or_equiv is None:
      B_iso_or_equiv = flex_double_else_none(
        cif_block.get('_atom_site_B_iso_or_equiv',
        cif_block.get('_atom_site_B_equiv_geom_mean')))
    adp_type = cif_block.get('_atom_site_adp_type')
    occupancy = flex_double_else_none(cif_block.get('_atom_site_occupancy'))
    scatterers = flex.xray_scatterer()
    atom_site_aniso_label = flex_std_string_else_none(
      cif_block.get('_atom_site_aniso_label'))
    if atom_site_aniso_label is not None:
      atom_site_aniso_label = atom_site_aniso_label
      adps = [cif_block.get('_atom_site_aniso_U_%i' %i)
              for i in (11,22,33,12,13,23)]
      have_Bs = False
      if adps.count(None) > 0:
        adps = [cif_block.get('_atom_site_aniso_B_%i' %i)
                for i in (11,22,33,12,13,23)]
        have_Bs = True
      if adps.count(None) == 6:
        adps = None
      elif adps.count(None) > 0:
        CifBuilderError("Some ADP items are missing")
      else:
        sel = None
        for adp in adps:
          f = (adp == "?")
          if (sel is None): sel = f
          else:             sel &= f
        sel = ~sel
        atom_site_aniso_label = atom_site_aniso_label.select(sel)
        try:
          adps = [flex.double(adp.select(sel)) for adp in adps]
        except ValueError as e:
          raise CifBuilderError("Error interpreting ADPs: " + str(e))
        adps = flex.sym_mat3_double(*adps)
    for i in range(len(atom_sites_frac)):
      kwds = {}
      if labels is not None:
        kwds.setdefault('label', str(labels[i]))
      if type_symbol is not None:
        kwds.setdefault('scattering_type', str(type_symbol[i]))
      if (atom_site_aniso_label is not None
          and adps is not None
          and labels is not None
          and labels[i] in atom_site_aniso_label):
        adp = adps[flex.first_index(atom_site_aniso_label, labels[i])]
        if have_Bs: adp = adptbx.b_as_u(adp)
        kwds.setdefault('u', adptbx.u_cif_as_u_star(
          self.crystal_symmetry.unit_cell(), adp))
      elif U_iso_or_equiv is not None:
        kwds.setdefault('u', float_from_string(U_iso_or_equiv[i]))
      elif B_iso_or_equiv is not None:
        kwds.setdefault('b', float_from_string(B_iso_or_equiv[i]))
      if occupancy is not None:
        kwds.setdefault('occupancy', float_from_string(occupancy[i]))
      scatterers.append(xray.scatterer(**kwds))
    scatterers.set_sites(atom_sites_frac)

    wvl_str = self.get_cif_item('_diffrn_radiation_wavelength')
    if not isinstance(wvl_str, str) and wvl_str is not None:
      wvl_str = wvl_str[0]
    wavelength = float_from_string(wvl_str) if (wvl_str and wvl_str!='?') else None

    self.structure = xray.structure(crystal_symmetry=self.crystal_symmetry,
                                    scatterers=scatterers,
                                    wavelength=wavelength)


class miller_array_builder(crystal_symmetry_builder):

  observation_types = {
    # known types of column data to be tagged as either amplitudes or intensities as per
    # https://www.iucr.org/__data/iucr/cifdic_html/2/cif_mm.dic/index.html
    '_refln.F_squared': xray.intensity(),
    '_refln_F_squared': xray.intensity(),
    '_refln.intensity': xray.intensity(),
    '_refln.I(+)': xray.intensity(),
    '_refln.I(-)': xray.intensity(),
    '_refln.F_calc': xray.amplitude(),
    '_refln.F_meas': xray.amplitude(),
    '_refln.FP': xray.amplitude(),
    '_refln.F-obs': xray.amplitude(),
    '_refln.Fobs': xray.amplitude(),
    '_refln.F-calc': xray.amplitude(),
    '_refln.Fcalc': xray.amplitude(),
  }

  def __init__(self, cif_block, base_array_info=None, wavelengths=None, style="classic"):
    self._arrays = OrderedDict()
    self._origarrays = OrderedDict()
    if style == "classic": # parsing of data labels using original constructor
      self.init(cif_block, base_array_info, wavelengths)
    if style == "new": # regular expressions for parsing data labels and associating columns appropriately
      self.init_new(cif_block, base_array_info, wavelengths)

  def init(self, cif_block, base_array_info=None, wavelengths=None):
    crystal_symmetry_builder.__init__(self, cif_block)
    if base_array_info is not None:
      self.crystal_symmetry = self.crystal_symmetry.join_symmetry(
        other_symmetry=base_array_info.crystal_symmetry_from_file,
      force=True)
    if (wavelengths is None):
      wavelengths = {}
    if base_array_info is None:
      base_array_info = miller.array_info(source_type="cif")
    refln_containing_loops = self.get_miller_indices_containing_loops()

    for self.indices, refln_loop in refln_containing_loops:
      self.wavelength_id_array = None
      self.crystal_id_array = None
      self.scale_group_array = None
      wavelength_ids = [None]
      crystal_ids = [None]
      scale_groups = [None]
      for key, value in six.iteritems(refln_loop):
        # need to get these arrays first
        if (key.endswith('wavelength_id') or
            key.endswith('crystal_id') or
            key.endswith('scale_group_code')):
          data = as_int_or_none_if_all_question_marks(value, column_name=key)
          if data is None:
            continue
          counts = data.counts()
          if key.endswith('wavelength_id'):
            wavelength_ids = list(counts.keys())
          if len(counts) == 1: continue
          array = miller.array(
            miller.set(self.crystal_symmetry, self.indices).auto_anomalous(), data)
          if key.endswith('wavelength_id'):
            self.wavelength_id_array = array
            wavelength_ids = list(counts.keys())
          elif key.endswith('crystal_id'):
            self.crystal_id_array = array
            crystal_ids = list(counts.keys())
          elif key.endswith('scale_group_code'):
            self.scale_group_array = array
            scale_groups = list(counts.keys())
      for label, value in sorted(refln_loop.items()):
        for w_id in wavelength_ids:
          for crys_id in crystal_ids:
            for scale_group in scale_groups:
              if 'index_' in label: continue
              key = label
              labels = [label]
              wavelength = None
              if (key.endswith('wavelength_id') or
                    key.endswith('crystal_id') or
                    key.endswith('scale_group_code')):
                w_id = None
                crys_id = None
                scale_group = None
              key_suffix = ''
              if w_id is not None:
                key_suffix += '_%i' %w_id
                labels.insert(0, "wavelength_id=%i" %w_id)
                wavelength = wavelengths.get(w_id, None)
              if crys_id is not None:
                key_suffix += '_%i' %crys_id
                labels.insert(0, "crystal_id=%i" %crys_id)
              if scale_group is not None:
                key_suffix += '_%i' %scale_group
                labels.insert(0, "scale_group_code=%i" %scale_group)
              key += key_suffix
              sigmas = None
              if key in self._arrays: continue
              array = self.flex_std_string_as_miller_array(
                value, wavelength_id=w_id, crystal_id=crys_id,
                scale_group_code=scale_group)
              if array is None: continue
              if '_sigma' in key:
                sigmas_label = label
                key = None
                for suffix in ('', '_meas', '_calc'):
                  if sigmas_label.replace('_sigma', suffix) in refln_loop:
                    key = sigmas_label.replace('_sigma', suffix) + key_suffix
                    break
                if key is None:
                  key = sigmas_label + key_suffix
                elif key in self._arrays and self._arrays[key].sigmas() is None:
                  sigmas = array
                  array = self._arrays[key]
                  if(not check_array_sizes(array, sigmas, key, sigmas_label)):
                    continue
                  sigmas = as_flex_double(sigmas, sigmas_label)
                  array.set_sigmas(sigmas.data())
                  info = array.info()
                  array.set_info(
                    info.customized_copy(labels=info.labels+[sigmas_label],
                      wavelength=wavelength))
                  continue
              elif 'PHWT' in key:
                phwt_label = label
                fwt_label = label.replace('PHWT', 'FWT')
                if fwt_label not in refln_loop: continue
                phwt_array = array
                if fwt_label in self._arrays:
                  array = self._arrays[fwt_label]
                  if(not check_array_sizes(array, phwt_array, fwt_label, phwt_label)):
                    continue
                  phases = as_flex_double(phwt_array, phwt_label)
                  info = array.info()
                  array = array.phase_transfer(phases, deg=True)
                  array.set_info(
                    info.customized_copy(labels=info.labels+[phwt_label]))
                  self._arrays[fwt_label] = array
                  continue
              elif 'HL_' in key:
                hl_letter = key[key.find('HL_')+3]
                hl_key = 'HL_' + hl_letter
                key = key.replace(hl_key, 'HL_A')
                if key in self._arrays:
                  continue # this array is already dealt with
                hl_labels = [label.replace(hl_key, 'HL_'+letter) for letter in 'ABCD']
                hl_keys = [key.replace(hl_key, 'HL_'+letter) for letter in 'ABCD']
                hl_values = [cif_block.get(hl_key) for hl_key in hl_labels]
                if hl_values.count(None) == 0:
                  selection = self.get_selection(
                    hl_values[0], wavelength_id=w_id,
                    crystal_id=crys_id, scale_group_code=scale_group)
                  hl_values = [as_double_or_none_if_all_question_marks(
                    hl.select(selection), column_name=lab)
                               for hl, lab in zip(hl_values, hl_labels)]
                  array = miller.array(miller.set(
                    self.crystal_symmetry, self.indices.select(selection)
                    ).auto_anomalous(), flex.hendrickson_lattman(*hl_values))
                  labels = labels[:-1]+hl_labels
              elif '.B_' in key or '_B_' in key:
                if '.B_' in key:
                  key, key_b = key.replace('.B_', '.A_'), key
                  label, label_b = label.replace('.B_', '.A_'), label
                elif '_B_' in key:
                  key, key_b = key.replace('_B', '_A'), key
                  label, label_b = label.replace('_B', '_A'), label
                if key in refln_loop and key_b in refln_loop:
                  b_part = array.data()
                  if key in self._arrays:
                    info = self._arrays[key].info()
                    a_part = self._arrays[key].data()
                    self._arrays[key] = self._arrays[key].array(
                      data=flex.complex_double(a_part, b_part))
                    self._arrays[key].set_info(
                      info.customized_copy(labels=info.labels+[key_b]))
                    continue
              elif ('phase_' in key and not "_meas" in key and
                    self.crystal_symmetry.space_group() is not None):
                alt_key1 = label.replace('phase_', 'F_')
                alt_key2 = alt_key1 + '_au'
                if alt_key1 in refln_loop:
                  phase_key = label
                  key = alt_key1+key_suffix
                elif alt_key2 in refln_loop:
                  phase_key = label
                  key = alt_key2+key_suffix
                else: phase_key = None
                if phase_key is not None:
                  phases = array.data()
                  if key in self._arrays:
                    array = self._arrays[key]
                    array = as_flex_double(array, key)
                    if(not check_array_sizes(array, phases, key, phase_key)):
                      continue
                    info = self._arrays[key].info()
                    self._arrays[key] = array.phase_transfer(phases, deg=True)
                    self._arrays[key].set_info(
                      info.customized_copy(labels=info.labels+[phase_key]))
                  else:
                    array = self.flex_std_string_as_miller_array(
                      refln_loop[label], wavelength_id=w_id, crystal_id=crys_id,
                      scale_group_code=scale_group)
                    if(not check_array_sizes(array, phases, key, phase_key)):
                      continue
                    array.phase_transfer(phases, deg=True)
                    labels = labels+[label, phase_key]
              if base_array_info.labels is not None:
                labels = base_array_info.labels + labels
              def rstrip_substrings(string, substrings):
                for substr in substrings:
                  if substr == '': continue
                  if string.endswith(substr):
                    string = string[:-len(substr)]
                return string
              # determine observation type
              stripped_key = rstrip_substrings(
                key, [key_suffix, '_au', '_meas', '_calc', '_plus', '_minus'])
              if (stripped_key.endswith('F_squared') or
                  stripped_key.endswith('intensity') or
                  stripped_key.endswith('.I') or
                  stripped_key.endswith('_I')) and (
                    array.is_real_array() or array.is_integer_array()):
                array.set_observation_type_xray_intensity()
              elif (stripped_key.endswith('F') and (
                array.is_real_array() or array.is_integer_array())):
                array.set_observation_type_xray_amplitude()
              if (array.is_xray_amplitude_array() or
                  array.is_xray_amplitude_array()):
                # e.g. merge_equivalents treats integer arrays differently, so must
                # convert integer observation arrays here to be safe
                if isinstance(array.data(), flex.int):
                  array = array.customized_copy(data=array.data().as_double())
              array.set_info(base_array_info.customized_copy(labels=labels))
              if (array.is_xray_amplitude_array() or
                  array.is_xray_amplitude_array()):
                info = array.info()
                array.set_info(info.customized_copy(wavelength=wavelength))
              self._arrays.setdefault(key, array)
    for key, array in six.iteritems(self._arrays.copy()):
      if (   key.endswith('_minus') or '_minus_' in key
          or key.endswith('_plus') or '_plus_' in key):
        if '_minus' in key:
          minus_key = key
          plus_key = key.replace('_minus', '_plus')
        elif '_plus' in key:
          plus_key = key
          minus_key = key.replace('_plus', '_minus')
        if plus_key in self._arrays and minus_key in self._arrays:
          plus_array = self._arrays.pop(plus_key)
          minus_array = self._arrays.pop(minus_key)
          minus_array = minus_array.customized_copy(
            indices=-minus_array.indices()).set_info(minus_array.info())
          array = plus_array.concatenate(
            minus_array, assert_is_similar_symmetry=False)
          array = array.customized_copy(anomalous_flag=True)
          array.set_info(minus_array.info().customized_copy(
            labels=list(
              OrderedSet(plus_array.info().labels+minus_array.info().labels))))
          array.set_observation_type(plus_array.observation_type())
          self._arrays.setdefault(key, array)

    if len(self._arrays) == 0:
      raise CifBuilderError("No reflection data present in cif block")


  def init_new(self, cif_block, base_array_info=None, wavelengths=None):
    """
    Using regular expression for parsing data labels adn associating data columns
    appropriately
    """
    crystal_symmetry_builder.__init__(self, cif_block)
    if base_array_info is not None:
      self.crystal_symmetry = self.crystal_symmetry.join_symmetry(
        other_symmetry=base_array_info.crystal_symmetry_from_file,
      force=True)
    if (wavelengths is None):
      wavelengths = {}
    if base_array_info is None:
      base_array_info = miller.array_info(source_type="cif")
    refln_containing_loops = self.get_miller_indices_containing_loops()
    for self.indices, refln_loop in refln_containing_loops:
      self.wavelength_id_array = None
      self.crystal_id_array = None
      self.scale_group_array = None
      wavelength_ids = [None]
      crystal_ids = [None]
      scale_groups = [None]
      for key, value in six.iteritems(refln_loop):
        # need to get these arrays first
        if (key.endswith('wavelength_id') or
            key.endswith('crystal_id') or
            key.endswith('scale_group_code')):
          data = as_int_or_none_if_all_question_marks(value, column_name=key)
          if data is None:
            continue
          counts = data.counts()
          if key.endswith('wavelength_id'):
            wavelength_ids = list(counts.keys())
          if len(counts) == 1: continue
          array = miller.array(
            miller.set(self.crystal_symmetry, self.indices).auto_anomalous(), data)
          if key.endswith('wavelength_id'):
            self.wavelength_id_array = array
            wavelength_ids = list(counts.keys())
          elif key.endswith('crystal_id'):
            self.crystal_id_array = array
            crystal_ids = list(counts.keys())
          elif key.endswith('scale_group_code'):
            self.scale_group_array = array
            scale_groups = list(counts.keys())
        # replace ? with nan to retain same number of reflections in all miller arrays
        for i,e in enumerate(value):
          if e=="?":
            value[i]="nan"

      labelsuffix = ""
      wavestr = ""
      crysstr = ""
      scalegrpstr = ""
      self._origarrays["HKLs"] = self.indices
      alllabels = list(refln_loop.keys())
      remaininglabls = alllabels[:]
      for w_id in wavelength_ids:
        for crys_id in crystal_ids:
          for scale_group in scale_groups:
            # If reflection data files contain more than one crystal, wavelength or scalegroup
            # then add the value(s) as a suffix to data labels computed below.
            if len(wavelength_ids) > 1:
              wavestr = ",wavelength_id=%i" %w_id
            if len(crystal_ids) > 1:
              crysstr = ",crys_id=%i" %crys_id
            if len(scale_groups) > 1:
              scalegrpstr += ",scale_group=%i" %scale_group
            labelsuffix = wavestr + crysstr + scalegrpstr
            data_sig_obstype_labls, remaininglabls = self.get_FSigF_ISigI_labels(remaininglabls)
            for datlabl,siglabl,otype in data_sig_obstype_labls:
              datastrarray = refln_loop[datlabl]
              sigmasstrarray = refln_loop[siglabl]
              millarr = self.flex_std_string_as_miller_array(
                datastrarray, wavelength_id=w_id, crystal_id=crys_id,
                scale_group_code=scale_group)
              sigmas = self.flex_std_string_as_miller_array(
                sigmasstrarray, wavelength_id=w_id, crystal_id=crys_id,
                scale_group_code=scale_group)
              millarr.set_sigmas(sigmas.data())
              datsiglabl = [datlabl, siglabl]
              if labelsuffix:
                datsiglabl = [datlabl, siglabl, labelsuffix]
              millarr.set_info(base_array_info.customized_copy(labels= datsiglabl,
                                                              wavelength=wavelengths.get(w_id, None)))
              if otype is not None:
                millarr.set_observation_type(otype)
              self._arrays[millarr.info().label_string() ] = millarr
            mapcoefflabls, remaininglabls = self.get_mapcoefficient_labels(remaininglabls)
            for mapcoefflabl in mapcoefflabls:
              amplitudestrarray = refln_loop[ mapcoefflabl[0] ]
              phasestrarray = refln_loop[ mapcoefflabl[1] ]
              millarr = self.flex_std_string_as_miller_array(
                amplitudestrarray, wavelength_id=w_id, crystal_id=crys_id,
                scale_group_code=scale_group)
              phasesmillarr = self.flex_std_string_as_miller_array(
                phasestrarray, wavelength_id=w_id, crystal_id=crys_id,
                scale_group_code=scale_group)
              phases = as_flex_double(phasesmillarr, mapcoefflabl[1])
              millarr = millarr.phase_transfer(phases, deg=True)
              if labelsuffix:
                mapcoefflabl = mapcoefflabl + [labelsuffix]
              millarr.set_info(base_array_info.customized_copy(labels= mapcoefflabl ,
                                                              wavelength=wavelengths.get(w_id, None)))
              self._arrays[millarr.info().label_string() ] = millarr
            HLcoefflabls, remaininglabls = self.get_HL_labels(remaininglabls)
            for hl_labels in HLcoefflabls:
              hl_values = [cif_block.get(hl_key) for hl_key in hl_labels]
              if hl_values.count(None) == 0:
                selection = self.get_selection(
                  hl_values[0], wavelength_id=w_id,
                  crystal_id=crys_id, scale_group_code=scale_group)
                hl_values = [as_double_or_none_if_all_question_marks(
                  hl.select(selection), column_name=lab)
                              for hl, lab in zip(hl_values, hl_labels)]

                millarr = miller.array(miller.set(
                  self.crystal_symmetry, self.indices.select(selection)
                  ).auto_anomalous(), flex.hendrickson_lattman(*hl_values))
                if labelsuffix:
                  hl_labels = hl_labels + [labelsuffix]
                millarr.set_info(base_array_info.customized_copy(labels= hl_labels,
                                                                wavelength=wavelengths.get(w_id, None)))
                self._arrays[millarr.info().label_string() ] = millarr
            for label in alllabels:
              if (label.endswith('wavelength_id') or
                  label.endswith('crystal_id') or
                  label.endswith('scale_group_code') or
                  'index_' in label):
                continue
              datastrarray = refln_loop[label]
              if label in remaininglabls:
                millarr = self.flex_std_string_as_miller_array(
                  datastrarray, wavelength_id=w_id, crystal_id=crys_id,
                  scale_group_code=scale_group)
                labels = [label]
                if labelsuffix:
                  labels = [label] + [labelsuffix]
                millarr.set_info(base_array_info.customized_copy(labels= labels,
                                                                wavelength=wavelengths.get(w_id, None)))
                self._arrays[millarr.info().label_string() ] = millarr
              try:
                origarr = flex.double(datastrarray)
              except ValueError as  e:
                origarr = datastrarray
              newlabel = label.replace("_refln.", "")
              newlabel = label.replace("_refln_", "")
              self._origarrays[newlabel + labelsuffix] = origarr

    for key, array in six.iteritems(self._arrays.copy()):
      if (   key.endswith('_minus') or '_minus_' in key or '-' in key
          or key.endswith('_plus') or '_plus_' in key or '+' in key):
        if '_minus' in key:
          minus_key = key
          plus_key = key.replace('_minus', '_plus')
        elif '-' in key:
          minus_key = key
          plus_key = key.replace('-', '+')
        elif '_plus' in key:
          plus_key = key
          minus_key = key.replace('_plus', '_minus')
        elif '+' in key:
          plus_key = key
          minus_key = key.replace('+', '-')
        if plus_key in self._arrays and minus_key in self._arrays:
          plus_array = self._arrays.pop(plus_key)
          minus_array = self._arrays.pop(minus_key)
          minus_array = minus_array.customized_copy(
            indices=-minus_array.indices()).set_info(minus_array.info())
          array = plus_array.concatenate(
            minus_array, assert_is_similar_symmetry=False)
          array = array.customized_copy(anomalous_flag=True)
          array.set_info(minus_array.info().customized_copy(
            labels=list(
              OrderedSet(plus_array.info().labels+minus_array.info().labels))))
          array.set_observation_type(plus_array.observation_type())
          self._arrays.setdefault(key, array)

    if len(self._arrays) == 0:
      raise CifBuilderError("No reflection data present in cif block")


  def get_HL_labels(self, keys):
    lstkeys = list(keys) # cast into list if not a list
    HLquads = []
    alllabels = " ".join(lstkeys)
    """ Hendrickson-Lattmann labels could look like: 'HLAM', 'HLBM', 'HLCM', 'HLDM'
    or like 'HLanomA', 'HLanomB', 'HLanomC', 'HLanomD'
    Use a regular expression to group them accordingly
    """
    allmatches = re.findall("(\S*(HL(\S*)[abcdABCD](\S*)))", alllabels )
    HLtagslst = list(set([ (e[2], e[3]) for e in allmatches ]))
    usedkeys = []
    for m in HLtagslst:
      hllist = []
      for hm in allmatches:
        if m==(hm[2], hm[3]):
          hllist.append((hm[0], hm[1]))
      if len(hllist) == 4:
        HLquads.append([ e[0] for e in hllist])
        for e in hllist:
          usedkeys.append(e[0])
    remainingkeys = []
    for e in lstkeys:
      if e not in usedkeys:
        remainingkeys.append(e)
    return HLquads, remainingkeys


  def get_mapcoefficient_labels(self, keys):
    lstkeys = list(keys) # cast into list if not a list
    remainingkeys = lstkeys[:] # deep copy the list
    alllabels = " ".join(lstkeys) #  _refln.FC _refln.PHIC _refln.FC_ALL _refln.PHIC_ALL _refln.FWT _refln.PHWT _refln.DELFWT _refln.PHDELWT
    mapcoefflabels = []
    PHmatches = re.findall("((\S*PH)([^I]\S*))", alllabels ) # [('_refln.PHWT', '_refln.PH', 'WT'), ('_refln.PHDELWT', '_refln.PH', 'DELWT')]
    for label in lstkeys:
      for m in PHmatches:
        Flabel = m[1].replace("PH","F") + m[2]
        if Flabel == label:
          mapcoefflabels.append([ label, m[0]])
          remainingkeys.remove(label)
          remainingkeys.remove(m[0])
    alllabels = " ".join(remainingkeys)
    PHImatches = re.findall("((\S*PHI)(\S*))", alllabels ) # [('_refln.PHIC', '_refln.PHI', 'C'), ('_refln.PHIC_ALL', '_refln.PHI', 'C_ALL')]
    for label in lstkeys:
      for m in PHImatches:
        Flabel = m[1].replace("PHI","F") + m[2]
        if Flabel == label:
          mapcoefflabels.append([ label, m[0]])
          remainingkeys.remove(label)
          remainingkeys.remove(m[0])
    alllabels = " ".join(remainingkeys)
    PHDELmatches = re.findall("(((\S*)PH)([^I]\S*(WT)))", alllabels ) # [('_refln.PHDELWT', '_refln.PH', '_refln.', 'DELWT', 'WT')]
    for label in lstkeys:
      for m in PHDELmatches:
        Flabel = m[2] + m[3].replace("WT","FWT")
        if Flabel == label:
          mapcoefflabels.append([ label, m[0]])
          remainingkeys.remove(label)
          remainingkeys.remove(m[0])
    alllabels = " ".join(remainingkeys)
    phase_matches = re.findall("((\S*\.)phase(_\S*))", alllabels ) # [('_refln.phase_calc', '_refln.', '')]
    for label in lstkeys:
      for m in phase_matches:
        phaselabel = m[0]
        Flabel = m[1] + "F" + m[2]
        if Flabel in label: # in case of _refln.F_calc_au and _refln.phase_calc
          mapcoefflabels.append([ label, m[0]])
          remainingkeys.remove(label)
          remainingkeys.remove(m[0])
    return mapcoefflabels, remainingkeys


  def get_FSigF_ISigI_labels(self, keys):
    lstkeys = list(keys) # cast into list if not a list
    remainingkeys = lstkeys[:] # deep copy the list
    alllabels = " ".join(lstkeys) #  _refln.FC _refln.PHIC _refln.FC_ALL _refln.PHIC_ALL _refln.FWT _refln.PHWT _refln.DELFWT _refln.PHDELWT
    labelpairs = []
    def guess_observationtype(labl):
      for okey in list(self.observation_types.keys()):
        if labl.startswith(okey):
          return self.observation_types[okey]
      return None
    sigma_matches = re.findall("((\S*\.)SIG(\S*))", alllabels ) # catch label pairs like F(+),SIGF(+)
    for label in lstkeys:
      for m in sigma_matches:
        FIlabel = m[1] + m[2]
        if FIlabel == label:
          labelpairs.append([ label, m[0], guess_observationtype(label)])
          remainingkeys.remove(label)
          remainingkeys.remove(m[0])
    alllabels = " ".join(remainingkeys)
    sigma_matches = re.findall("((\S*)_sigma(_*\S*))", alllabels ) # [('_refln.F_meas_sigma_au', '_refln.F_meas', '_au'), ('_refln.intensity_sigma', '_refln.intensity', ''), ('_refln.pdbx_I_plus_sigma', '_refln.pdbx_I_plus', '')]
    for label in lstkeys:
      for m in sigma_matches:
        FIlabel = m[1] + m[2]
        if FIlabel == label:
          labelpairs.append([ label, m[0], guess_observationtype(label)])
          remainingkeys.remove(label)
          remainingkeys.remove(m[0])
    alllabels = " ".join(remainingkeys)
    # catch generic meas and sigma labels, https://www.iucr.org/__data/iucr/cifdic_html/2/cif_mm.dic/index.html
    anymeas_matches = re.findall("((\S*)_meas(\S*))", alllabels ) + re.findall("((\S*)_calc(\S*))", alllabels )
    anysigma_matches = re.findall("((\S*)_sigma(\S*))", alllabels )
    for mmatch in anymeas_matches:
      for smatch in anysigma_matches:
        if mmatch[1]==smatch[1] and mmatch[2]==smatch[2]:
          labelpairs.append([ mmatch[0], smatch[0], guess_observationtype(mmatch[0])])
          remainingkeys.remove(mmatch[0])
          if smatch[0] in remainingkeys: # in case of say F_squared_calc, F_squared_meas, F_squared_sigma all being present
            remainingkeys.remove(smatch[0])
    return labelpairs, remainingkeys


  def get_miller_indices_containing_loops(self):
    loops = []
    for loop in self.cif_block.loops.values():
      for key in loop.keys():
        if 'index_h' not in key: continue
        hkl_str = [loop.get(key.replace('index_h', 'index_%s' %i)) for i in 'hkl']
        if hkl_str.count(None) > 0:
          raise CifBuilderError(
            "Miller indices missing from current CIF block (%s)"
            %key.replace('index_h', 'index_%s' %'hkl'[hkl_str.index(None)]))
        hkl_int = []
        for i,h_str in enumerate(hkl_str):
          try:
            h_int = flex.int(h_str)
          except ValueError as e:
            raise CifBuilderError(
              "Invalid item for Miller index %s: %s" % ("HKL"[i], str(e)))
          hkl_int.append(h_int)
        indices = flex.miller_index(*hkl_int)
        loops.append((indices, loop))
        break
    return loops

  def get_selection(self, value,
                    wavelength_id=None,
                    crystal_id=None,
                    scale_group_code=None):
    selection = ~((value == '.') | (value == '?'))
    if self.wavelength_id_array is not None and wavelength_id is not None:
      selection &= (self.wavelength_id_array.data() == wavelength_id)
    if self.crystal_id_array is not None and crystal_id is not None:
      selection &= (self.crystal_id_array.data() == crystal_id)
    if self.scale_group_array is not None and scale_group_code is not None:
      selection &= (self.scale_group_array.data() == scale_group_code)
    return selection

  def flex_std_string_as_miller_array(self, value,
                                      wavelength_id=None,
                                      crystal_id=None,
                                      scale_group_code=None):
    selection = self.get_selection(
      value, wavelength_id=wavelength_id,
      crystal_id=crystal_id, scale_group_code=scale_group_code)
    data = value.select(selection)
    try:
      data = flex.int(data)
      indices = self.indices.select(selection)
    except ValueError:
      try:
        data = flex.double(data)
        indices = self.indices.select(selection)
      except ValueError:
        # if flex.std_string return all values including '.' and '?'
        data = value
        indices = self.indices
    if data.size() == 0: return None
    return miller.array(
      miller.set(self.crystal_symmetry, indices).auto_anomalous(), data)

  def arrays(self):
    return self._arrays

  def origarrays(self):
    """
    return dictionary of raw data found in cif file cast into flex.double arrays
    or just string arrays as a fall back.
    """
    return self._origarrays


def as_flex_double(array, key):
  if isinstance(array.data(), flex.double):
    return array
  elif isinstance(array.data(), flex.int):
    return array.customized_copy(
      data=array.data().as_double()).set_info(array.info())
  else:
    try:
      flex.double(array.data())
    except ValueError as e:
      e_str = str(e)
      if e_str.startswith("Invalid floating-point value: "):
        i = e_str.find(":") + 2
        raise CifBuilderError("Invalid floating-point value for %s: %s"
                              %(key, e_str[i:].strip()))
      else:
        raise CifBuilderError(e_str)

def check_array_sizes(array1, array2, key1, key2):
  if array1.size() != array2.size():
    msg = "Miller arrays '%s' and '%s' are of different sizes" %(key1, key2)
    CifBuilderWarning(message=msg)
    return False
  return True

def none_if_all_question_marks_or_period(cif_block_item):
  if (cif_block_item is None): return None
  result = cif_block_item
  if (result.all_eq("?")): return None
  elif (result.all_eq(".")): return None
  return result

def as_int_or_none_if_all_question_marks(cif_block_item, column_name=None):
  strings = none_if_all_question_marks_or_period(cif_block_item)
  if (strings is None): return None
  try:
    return flex.int(strings)
  except ValueError as e:
    # better error message if column_name is given
    e_str = str(e)
    if column_name is not None and e_str.startswith(
      "Invalid integer value: "):
      i = e_str.find(":") + 2
      raise CifBuilderError("Invalid integer value for %s: %s"
                            %(column_name, e_str[i:].strip()))
    else:
      raise CifBuilderError(e_str)

def as_double_or_none_if_all_question_marks(cif_block_item, column_name=None):
  strings = none_if_all_question_marks_or_period(cif_block_item)
  if (strings is None): return None
  try:
    return flex.double(strings)
  except ValueError as e:
    # better error message if column_name is given
    e_str = str(e)
    if column_name is not None and e_str.startswith(
      "Invalid floating-point value: "):
      i = e_str.find(":") + 2
      raise CifBuilderError("Invalid floating-point value for %s: %s"
                            %(column_name, e_str[i:].strip()))
    else:
      raise CifBuilderError(e_str)

def flex_double(flex_std_string):
  try:
    return flex.double(flex_std_string)
  except ValueError as e:
    raise CifBuilderError(str(e))

def flex_double_else_none(cif_block_item):
  strings = none_if_all_question_marks_or_period(cif_block_item)
  if (strings is None): return None
  try:
    return flex.double(strings)
  except ValueError:
    pass
  return None

def flex_std_string_else_none(cif_block_item):
  if isinstance(cif_block_item, flex.std_string):
    return cif_block_item
  else:
    return None

def float_from_string(string):
  """a cif string may be quoted,
and have an optional esd in brackets associated with it"""
  if isinstance(string, float):
    return string
  return float(string.strip('\'').strip('"').split('(')[0])

def get_wavelengths(cif_block):
  for loop in cif_block.loops.values():
    for key in loop.keys():
      if ("_diffrn_radiation_wavelength." in key):
        wavelength_ids = loop.get("_diffrn_radiation_wavelength.id")
        wavelength_strs = loop.get("_diffrn_radiation_wavelength.wavelength")
        if (not None in [wavelength_ids, wavelength_strs]):
          wl_ = {}
          for wavelength_id,wavelength in zip(wavelength_ids,wavelength_strs):
            try :
              wl_id = int(wavelength_id)
              wl_[int(wavelength_id)] = float(wavelength)
            except ValueError :
              pass
          return wl_
        else :
          return None
  wavelength_id = cif_block.get("_diffrn_radiation_wavelength.id")
  wavelength_str = cif_block.get("_diffrn_radiation_wavelength.wavelength")
  if (not None in [wavelength_id, wavelength_str]):
    try :
      wl_id = int(wavelength_id)
      return { int(wavelength_id) : float(wavelength_str) }
    except ValueError :
      pass
  return None
