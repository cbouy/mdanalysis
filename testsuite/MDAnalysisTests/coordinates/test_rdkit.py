# -*- Mode: python; tab-width: 4; indent-tabs-mode:nil; coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4 fileencoding=utf-8
#
# MDAnalysis --- https://www.mdanalysis.org
# Copyright (c) 2006-2017 The MDAnalysis Development Team and contributors
# (see the file AUTHORS for the full list of names)
#
# Released under the GNU Public Licence, v2 or any higher version
#
# Please cite your use of MDAnalysis in published work:
#
# R. J. Gowers, M. Linke, J. Barnoud, T. J. E. Reddy, M. N. Melo, S. L. Seyler,
# D. L. Dotson, J. Domanski, S. Buchoux, I. M. Kenney, and O. Beckstein.
# MDAnalysis: A Python package for the rapid analysis of molecular dynamics
# simulations. In S. Benthall and S. Rostrup editors, Proceedings of the 15th
# Python in Science Conference, pages 102-109, Austin, TX, 2016. SciPy.
# doi: 10.25080/majora-629e541a-00e
#
# N. Michaud-Agrawal, E. J. Denning, T. B. Woolf, and O. Beckstein.
# MDAnalysis: A Toolkit for the Analysis of Molecular Dynamics Simulations.
# J. Comput. Chem. 32 (2011), 2319--2327, doi:10.1002/jcc.21787
#

import pytest
import MDAnalysis as mda
from MDAnalysis.topology.guessers import guess_atom_element
from MDAnalysis.coordinates.RDKit import _infer_bo_and_charges
import numpy as np
from numpy.testing import (assert_equal,
                           assert_almost_equal)

from MDAnalysisTests.datafiles import mol2_molecule, PDB_full, GRO
from MDAnalysisTests.util import block_import, import_not_available


@block_import('rdkit')
class TestRequiresRDKit(object):
    def test_converter_requires_rdkit(self):
        u = mda.Universe(mol2_molecule)
        with pytest.raises(ImportError,
                           match="RDKit is required for the RDKitConverter"):
            u.atoms.convert_to("RDKIT")


try:
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from MDAnalysis.coordinates.RDKit import (
        RDATTRIBUTES, _add_mda_attr_to_rdkit)
except ImportError:
    def mol2_mol():
        pass

    def smiles_mol():
        pass
else:
    def mol2_mol():
        return Chem.MolFromMol2File(mol2_molecule, removeHs=False)

    def smiles_mol():
        mol = Chem.MolFromSmiles("CN1C=NC2=C1C(=O)N(C(=O)N2C)C")
        mol = Chem.AddHs(mol)
        cids = AllChem.EmbedMultipleConfs(mol, numConfs=3)
        return mol


requires_rdkit = pytest.mark.skipif(import_not_available("rdkit"),
                                    reason="requires RDKit")


@requires_rdkit
class TestRDKitReader(object):
    @pytest.mark.parametrize("rdmol, n_frames", [
        (mol2_mol(), 1),
        (smiles_mol(), 3),
    ])
    def test_coordinates(self, rdmol, n_frames):
        universe = mda.Universe(rdmol)
        assert universe.trajectory.n_frames == n_frames
        expected = np.array([
            conf.GetPositions() for conf in rdmol.GetConformers()],
            dtype=np.float32)
        assert_equal(expected, universe.trajectory.coordinate_array)

    def test_no_coordinates(self):
        with pytest.warns(UserWarning, match="No coordinates found"):
            u = mda.Universe.from_smiles("CCO", generate_coordinates=False)
        expected = np.empty((1, u.atoms.n_atoms, 3), dtype=np.float32)
        expected[:] = np.nan
        assert_equal(u.trajectory.coordinate_array, expected)

    def test_compare_mol2reader(self):
        universe = mda.Universe(mol2_mol())
        mol2 = mda.Universe(mol2_molecule)
        assert universe.trajectory.n_frames == mol2.trajectory.n_frames
        assert_equal(universe.trajectory.ts.positions,
                     mol2.trajectory.ts.positions)


@requires_rdkit
class TestRDKitConverter(object):
    @pytest.fixture
    def pdb(self):
        return mda.Universe(PDB_full)

    @pytest.fixture
    def mol2(self):
        u = mda.Universe(mol2_molecule)
        # add elements
        elements = np.array([guess_atom_element(x) for x in u.atoms.types],
                            dtype=object)
        u.add_TopologyAttr('elements', elements)
        return u

    @pytest.fixture
    def peptide(self):
        u = mda.Universe(GRO)
        elements = mda.topology.guessers.guess_types(u.atoms.names)
        u.add_TopologyAttr('elements', elements)
        return u.select_atoms("resid 2-12")

    @pytest.mark.parametrize("smi", ["[H]", "C", "O", "[He]"])
    def test_single_atom_mol(self, smi):
        u = mda.Universe.from_smiles(smi, addHs=False,
                                     generate_coordinates=False)
        mol = u.atoms.convert_to("RDKIT")
        assert mol.GetNumAtoms() == 1

    @pytest.mark.parametrize("resname, n_atoms, n_fragments", [
        ("PRO", 14, 1),
        ("ILE", 38, 1),
        ("ALA", 20, 2),
        ("GLY", 21, 3),
    ])
    def test_mol_from_selection(self, peptide, resname, n_atoms, n_fragments):
        mol = peptide.select_atoms("resname %s" % resname).convert_to("RDKIT")
        assert n_atoms == mol.GetNumAtoms()
        assert n_fragments == len(Chem.GetMolFrags(mol))

    @pytest.mark.parametrize("sel_str, atom_index", [
        ("resid 1", 0),
        ("resname LYS and name NZ", 1),
        ("resid 34 and altloc B", 2),
    ])
    def test_monomer_info(self, pdb, sel_str, atom_index):
        rdmol = Chem.MolFromPDBFile(PDB_full)
        sel = pdb.select_atoms(sel_str)
        umol = sel.convert_to("RDKIT")
        atom = umol.GetAtomWithIdx(atom_index)
        mi = atom.GetMonomerInfo()

        for mda_attr, rd_attr in RDATTRIBUTES.items():
            rd_value = getattr(mi, "Get%s" % rd_attr)()
            mda_value = getattr(sel, "%s" % mda_attr)[atom_index]
            if mda_attr == "names":
                rd_value = rd_value.strip()
            assert rd_value == mda_value

    def test_identical_topology_mol2(self, mol2):
        """Check stereochemistry on atoms and bonds (but not yet)"""
        rdmol = mol2_mol()
        umol = mol2.atoms.convert_to("RDKIT")
        assert rdmol.HasSubstructMatch(umol, useChirality=False)
        assert umol.HasSubstructMatch(rdmol, useChirality=False)

    def test_identical_topology(self):
        rdmol = smiles_mol()
        u = mda.Universe(rdmol)
        umol = u.atoms.convert_to("RDKIT")
        assert rdmol.HasSubstructMatch(umol) and umol.HasSubstructMatch(rdmol)

    def test_raise_requires_elements(self):
        u = mda.Universe(mol2_molecule)
        with pytest.raises(
            AttributeError,
            match="`elements` attribute is required for the RDKitConverter"
        ):
            u.atoms.convert_to("RDKIT")

    def test_warn_guess_bonds(self, pdb):
        pdb.delete_bonds(pdb.bonds)
        ag = pdb.select_atoms("resnum 101 and segid A")
        pdb.delete_bonds(ag.bonds)
        with pytest.warns(UserWarning, 
                          match="No `bonds` attribute in this AtomGroup"):
            ag.convert_to("RDKIT")

    @pytest.mark.parametrize("attr, value, expected", [
        ("names", "C1", " C1 "),
        ("names", "C12", " C12"),
        ("names", "Cl1", "Cl1 "),
        ("altLocs", "A", "A"),
        ("chainIDs", "B", "B"),
        ("icodes", "C", "C"),
        ("occupancies", 0.5, 0.5),
        ("resnames", "LIG", "LIG"),
        ("resids", 123, 123),
        ("segindices", 1, 1),
        ("tempfactors", 0.8, 0.8),
    ])
    def test_add_mda_attr_to_rdkit(self, attr, value, expected):
        mi = Chem.AtomPDBResidueInfo()
        _add_mda_attr_to_rdkit(attr, value, mi)
        rdvalue = getattr(mi, "Get%s" % RDATTRIBUTES[attr])()
        assert rdvalue == expected

    @pytest.mark.parametrize("idx", [0, 10, 42])
    def test_other_attributes(self, mol2, idx):
        mol = mol2.atoms.convert_to("RDKIT")
        rdprops = mol.GetAtomWithIdx(idx).GetPropsAsDict()
        for prop in ["charge", "segid", "type"]:
            rdprop = rdprops["_MDAnalysis_%s" % prop]
            mdaprop = getattr(mol2.atoms[idx], prop)
            assert rdprop == mdaprop

    @pytest.mark.parametrize("sel_str", [
        "resname ALA",
        "resname PRO and segid A",
    ])
    def test_index_property(self, pdb, sel_str):
        ag = pdb.select_atoms(sel_str)
        mol = ag.convert_to("RDKIT")
        expected = ag.indices
        indices = np.array([a.GetIntProp("_MDAnalysis_index")
                            for a in mol.GetAtoms()], dtype=np.int32)
        assert_equal(indices, expected)


@requires_rdkit
class TestRDKitFunctions(object):
    @pytest.mark.parametrize("smi, out", [
        ("[H]C([H])([H])[H]", "C"),
        ("[C]1(-[H])-[C](-[H])-[C](-[H])-[C](-[H])-[C](-[H])-[C]1(-[H])", "c1ccccc1"),
        ("[Cl]-[C](-[H])-[O]", "C(=O)Cl"),
        ("[H]-[C](-[O])-[N](-[H])-[H]", "C(=O)N"),
        ("[C](-[H])(-[H])-[C](-[H])-[H]", "C=C"),
        ("[P](-O)(-O)(-O)-[O]", "P(O)(O)(O)=O"),
        ("[N]-[C]-[H]", "N#C"),
    ])
    def test_infer_bond_orders(self, smi, out):
        mol = Chem.MolFromSmiles(smi, sanitize=False)
        mol.UpdatePropertyCache(strict=False)
        _infer_bo_and_charges(mol)
        mol = Chem.RemoveHs(mol)
        molref = Chem.MolFromSmiles(out)
        assert mol.HasSubstructMatch(
            molref) and molref.HasSubstructMatch(mol)

    @pytest.mark.skip(reason="not fully working yet")
    @pytest.mark.parametrize("smi, atom, charge", [
        ("C-[O]", "O", -1),
        ("[N]-[C]-[O]", "O", -1),
        ("[N](-[H])(-[H])(-[H])-[H]", "N", 1),
    ])
    def test_infer_charges(self, smi, atom, charge):
        mol = Chem.MolFromSmiles(smi, sanitize=False)
        mol.UpdatePropertyCache(strict=False)
        _infer_bo_and_charges(mol)
        index = mol.GetSubstructMatch(Chem.MolFromSmarts(atom))[0]
        assert mol.GetAtomWithIdx(index).GetFormalCharge() == charge
