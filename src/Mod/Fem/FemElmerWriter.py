# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2017 - Markus Hovorka <m.hovorka@live.de                *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************


__title__ = "FemWriterElmer"
__author__ = "Markus Hovorka, Bernd Hahnebach"
__url__ = "http://www.freecadweb.org"


## \addtogroup FEM
#  @{


from FreeCAD import Console
import os.path
import subprocess

import Units
import Fem
import FemMisc
import FemSettings
import ObjectsFem
import FemGmshTools
import FemDefsElmer
import sifio


_STARTINFO_NAME = "ELMERSOLVER_STARTINFO"
_SIF_NAME = "case.sif"
_ELMERGRID_IFORMAT = "8"
_ELMERGRID_OFORMAT = "2"
_SOLID_PREFIX = "Solid"


CONSTS_DEF = {
    "Gravity": 9.82,
    "StefanBoltzmann": 5.67e-8,
    "PermittivityOfVacuum": 8.8542e-12,
    "BoltzmannConstant": 1.3807e-23,
    "UnitCharge": 1.602e-19,
}


SUPPORTED = [
        ("Fem::ConstraintFixed",),
        ("Fem::ConstraintForce",),
        ("Fem::ConstraintDisplacement",),
        ("Fem::ConstraintTemperature",),
        ("Fem::ConstraintSelfWeight",),
        ("Fem::ConstraintInitialTemperature",),
        ("Fem::FeaturePython", "FemConstraintSelfWeight",),
]


class Writer(object):

    # The first parameter defines the input file format:
    #   1)  .grd      : Elmergrid file format
    #   2)  .mesh.*   : Elmer input format
    #   3)  .ep       : Elmer output format
    #   4)  .ansys    : Ansys input format
    #   5)  .inp      : Abaqus input format by Ideas
    #   6)  .fil      : Abaqus output format
    #   7)  .FDNEUT   : Gambit (Fidap) neutral file
    #   8)  .unv      : Universal mesh file format
    #   9)  .mphtxt   : Comsol Multiphysics mesh format
    #   10) .dat      : Fieldview format
    #   11) .node,.ele: Triangle 2D mesh format
    #   12) .mesh     : Medit mesh format
    #   13) .msh      : GID mesh format
    #   14) .msh      : Gmsh mesh format
    #   15) .ep.i     : Partitioned ElmerPost format
    #
    # The second parameter defines the output file format:
    #   1)  .grd      : ElmerGrid file format
    #   2)  .mesh.*   : ElmerSolver format (also partitioned .part format)
    #   3)  .ep       : ElmerPost format
    #   4)  .msh      : Gmsh mesh format
    #   5)  .vtu      : VTK ascii XML format
    #
    # The third parameter is the name of the input file.
    # If the file does not exist, an example with the same name is created.
    # The default output file name is the same with a different suffix.

    def __init__(self, analysis, solver, directory):
        self.analysis = analysis
        self.solver = solver
        self.directory = directory
        self._groupNames = dict()
        self._bndSections = dict()

    def writeInputFiles(self, report):
        self._purgeMeshGroups()
        self._writeSif()
        self._writeStartinfo()
        self._recreateMesh()
        self._writeMesh()

    def _recreateMesh(self):
        mesh = FemMisc.getSingleMember(self.analysis, "Fem::FemMeshObject")
        FemGmshTools.FemGmshTools(mesh).create_mesh()

    def _writeStartinfo(self):
        startinfo_path = os.path.join(
                self.directory, _STARTINFO_NAME)
        Console.PrintLog(
                "Write ELMERFEM_STARTINFO to {}.\n"
                .format(startinfo_path))
        with open(startinfo_path, 'w') as f:
            f.write(_SIF_NAME)

    def _writeMesh(self):
        unvPath = os.path.join(self.directory, "mesh.unv")
        mesh = FemMisc.getSingleMember(self.analysis, "Fem::FemMeshObject")
        Fem.export([mesh], unvPath)
        args = [FemSettings.getBinary("ElmerGrid"),
                _ELMERGRID_IFORMAT,
                _ELMERGRID_OFORMAT,
                unvPath,
                "-autoclean",
                "-out", self.directory]
        subprocess.call(args)

    def _purgeMeshGroups(self):
        mesh = FemMisc.getSingleMember(self.analysis, "Fem::FemMeshObject")
        for grp in mesh.MeshGroupList:
            grp.Document.removeObject(grp.Name)
        mesh.MeshGroupList = []

    def _getGroupName(self, subName):
        if subName in self._groupNames:
            return self._groupNames[subName]
        mesh = FemMisc.getSingleMember(self.analysis, "Fem::FemMeshObject")
        obj = ObjectsFem.makeMeshGroup(mesh, name=subName)
        obj.References += [(mesh.Part, (subName,))]
        self._groupNames[subName] = obj.Name
        return obj.Name

    def _writeSif(self):
        simulation = self._getSimulation()
        constants = self._getConstants()
        solvers = self._getSolvers()
        boundaryConditions = self._getBoundaryConditions()
        bodyForces = self._getBodyForces()
        initialConditions = self._getInitialConditions()
        equation = self._getEquation(solvers)

        bodyMaterial = dict.fromkeys(self._getSolidNames())
        materials = self._getMaterials(bodyMaterial)
        bodies = []
        for name, material in bodyMaterial.iteritems():
            bodies.append(self._getBody(
                    name, material, bodyForces, equation, initialConditions))

        sections = []
        sections.append(simulation)
        sections.append(constants)
        sections.extend(bodyForces)
        sections.extend(initialConditions)
        sections.extend(boundaryConditions)
        sections.extend(materials)
        sections.extend(solvers)
        sections.append(equation)
        sections.extend(bodies)

        sifPath = os.path.join(self.directory, _SIF_NAME)
        with open(sifPath, 'w') as fstream:
            sif = sifio.Sif(sections)
            sif.write(fstream)

    def _getSimulation(self):
        s = sifio.createSection(sifio.SIMULATION)
        s["Coordinate System"] = "Cartesian 3D"
        s["Coordinate Mapping"] = (1, 2, 3)
        s["Simulation Type"] = "Steady state"
        s["Steady State Max Iterations"] = 1
        s["Output Intervals"] = 1
        s["Timestepping Method"] = "BDF"
        s["BDF Order"] = 1
        s["Post File"] = sifio.FileAttr("case.vtu")
        s["Use Mesh Names"] = True
        return s

    def _getConstants(self):
        s = sifio.createSection(sifio.CONSTANTS)
        s["Gravity"] = (0.0, -1.0, 0.0, CONSTS_DEF["Gravity"])
        s["Stefan Boltzmann"] = CONSTS_DEF["StefanBoltzmann"]
        s["Permittivity of Vacuum"] = CONSTS_DEF["PermittivityOfVacuum"]
        s["Boltzmann Constant"] = CONSTS_DEF["BoltzmannConstant"]
        s["Unit Charge"] = CONSTS_DEF["UnitCharge"]
        return s

    def _getBodyForces(self):
        sections = []
        obj = FemMisc.getSingleMember(
                self.analysis, "Fem::FeaturePython", "FemConstraintSelfWeight")
        matObj = FemMisc.getSingleMember(self.analysis, "App::MaterialObjectPython")
        density = self._getInUnit(matObj.Material["Density"], "kg/mm^3")
        if obj is not None:
            sections.append(self._getSelfweight(obj, density))
        if self.solver.AnalysisType == FemDefsElmer.THERMOMECH:
            obj = FemMisc.getSingleMember(
                    self.analysis, "Fem::FeaturePython",
                    "FemConstraintBodyHeatFlux")
            if obj is not None:
                sections.append(self._getBodyHeatFlux(obj))
        return sections

    def _getBoundaryConditions(self):
        for obj in FemMisc.getMember(self.analysis, "Fem::ConstraintFixed"):
            self._createFixeds(obj)
        for obj in FemMisc.getMember(self.analysis, "Fem::ConstraintForce"):
            self._createForces(obj)
        for obj in FemMisc.getMember(self.analysis, "Fem::ConstraintDisplacement"):
            self._createDisplacements(obj)
        if self.solver.AnalysisType == FemDefsElmer.THERMOMECH:
            for obj in FemMisc.getMember(self.analysis, "Fem::ConstraintTemperature"):
                self._createTemps(obj)
        return self._bndSections.values()

    def _getInitialConditions(self):
        sections = []
        if self.solver.AnalysisType == FemDefsElmer.THERMOMECH:
            obj = FemMisc.getSingleMember(
                    self.analysis, "Fem::ConstraintInitialTemperature")
            if obj is not None:
                sections.append(self._getInitialTemp(obj))
        return sections

    def _getMaterials(self, bodyMaterials):
        sections = []
        for obj in FemMisc.getMember(self.analysis, "App::MaterialObjectPython"):
            s = self._getMaterialSection(obj)
            self._updateBodyMaterials(bodyMaterials, obj, s)
            sections.append(s)
        return sections

    def _getSolidNames(self):
        mesh = FemMisc.getSingleMember(
            self.analysis, "Fem::FemMeshObject")
        shape = mesh.Part.Shape
        return ["%s%d" % (_SOLID_PREFIX, i+1)
                for i in range(len(shape.Solids))]

    def _getMaterialSection(self, obj):
        m = obj.Material
        s = sifio.createSection(sifio.MATERIAL)
        s["Density"] = self._getInUnit(
                m["Density"], "kg/mm^3")
        s["Youngs Modulus"] = self._getInUnit(
                m["YoungsModulus"], "MPa")
        s["Poisson ratio"] = float(m["PoissonRatio"])
        s["Heat Conductivity"] = self._getInUnit(
                m["ThermalConductivity"], "W/mm/K")
        s["Heat expansion Coefficient"] = self._getInUnit(
                m["ThermalExpansionCoefficient"], "mm/mm/K")
        if self.solver.AnalysisType == FemDefsElmer.THERMOMECH:
            tempObj = FemMisc.getSingleMember(
                    self.analysis, "Fem::ConstraintInitialTemperature")
            if tempObj is not None:
                s["Reference Temperature"] = tempObj.initialTemperature
        return s

    def _updateBodyMaterials(self, bodyMaterials, obj, section):
        if len(obj.References) == 0:
            for name, material in dict(bodyMaterials).iteritems():
                bodyMaterials[name] = section
        else:
            for part, ref in obj.References:
                bodyMaterials[ref[0]] = section

    def _getSolvers(self):
        sections = []
        if self.solver.AnalysisType == FemDefsElmer.THERMOMECH:
            sections.append(self._getTermoSolver())
        sections.append(self._getElasticitySolver())
        return sections

    def _getElasticitySolver(self):
        s = sifio.createSection(sifio.SOLVER)
        s["Equation"] = "Linear elasticity"
        s["Procedure"] = sifio.FileAttr("StressSolve/StressSolver")
        s["Variable"] = "Displacement"
        s["Variable DOFs"] = 3
        s["Exec Solver"] = "Always"
        s["Stabilize"] = True
        s["Bubbles"] = False
        s["Optimize Bandwidth"] = True
        s["Steady State Convergence Tolerance"] = 1.0e-5
        s["Linear System Residual Output"] = 1
        if self.solver.AnalysisType == FemDefsElmer.FREQUENCY:
            s["Linear System Solver"] = "Direct"
            s["Eigen Analysis"] = True
            s["Eigen System Values"] = self.solver.EigenmodesCount
        else:
            s["Linear System Solver"] = "Iterative"
            s["Linear System Iterative Method"] = "BiCGStab"
            s["BiCGstabl polynomial degree"] = 2
            s["Linear System Max Iterations"] = \
                self.solver.LinMaxIterations
            s["Linear System Convergence Tolerance"] = \
                self.solver.LinConvergenceTolerance
            s["Linear System Preconditioning"] = "Diagonal"
            s["Linear System Precondition Recompute"] = 1
            s["Linear System Abort Not Converged"] = False
        return s

    def _getTermoSolver(self):
        s = sifio.createSection(sifio.SOLVER)
        s["Equation"] = "Heat Equation"
        s["Procedure"] = sifio.FileAttr("HeatSolve/HeatSolver")
        s["Variable"] = "Temperature"
        s["Exec Solver"] = "Always"
        s["Stabilize"] = True
        s["Bubbles"] = False
        s["Optimize Bandwidth"] = True
        s["Steady State Convergence Tolerance"] = 1.0e-5
        s["Nonlinear System Convergence Tolerance"] = \
            self.solver.TermoNLinConvergenceTolerance
        s["Nonlinear System Max Iterations"] = \
            self.solver.TermoNLinMaxIterations
        s["Nonlinear System Newton After Iterations"] = 3
        s["Nonlinear System Newton After Tolerance"] = 1.0e-3
        s["Nonlinear System Relaxation Factor"] = 1.0
        s["Linear System Solver"] = "Iterative"
        s["Linear System Iterative Method"] = "BiCGStab"
        s["Linear System Max Iterations"] = \
            self.solver.TermoLinMaxIterations
        s["Linear System Convergence Tolerance"] = \
            self.solver.TermoLinConvergenceTolerance
        s["Linear System Preconditioning"] = "Diagonal"
        s["Linear System Abort Not Converged"] = False
        s["Linear System Residual Output"] = 1
        s["Linear System Precondition Recompute"] = 1
        return s

    def _getEquation(self, solvers):
        s = sifio.createSection(sifio.EQUATION)
        s["Active Solvers"] = solvers
        return s

    def _getBody(self, name, material, bodyForces, equation, initial):
        s = sifio.createSection(sifio.BODY)
        s["Name"] = self._getGroupName(name)
        s["Material"] = material
        s["Equation"] = equation
        s["Body Force"] = bodyForces
        s["Initial Condition"] = initial
        return s

    def _getSelfweight(self, obj, density):
        s = sifio.createSection(sifio.BODY_FORCE)
        gravity = CONSTS_DEF["Gravity"]
        s["Stress Bodyforce 1"] = float(gravity * obj.Gravity_x * density)
        s["Stress Bodyforce 2"] = float(gravity * obj.Gravity_y * density)
        s["Stress Bodyforce 3"] = float(gravity * obj.Gravity_z * density)
        return s

    def _getBodyHeatFlux(self, obj):
        s = sifio.createSection(sifio.BODY_FORCE)
        s["Heat Source"] = float(obj.HeatFlux)
        return s

    def _createFixeds(self, obj):
        names = (self._getGroupName(x) for x in obj.References[0][1])
        for n in names:
            s = self._getBndSection(n)
            s["Displacement 1"] = 0.0
            s["Displacement 2"] = 0.0
            s["Displacement 3"] = 0.0

    def _createDisplacements(self, obj):
        names = [self._getGroupName(x) for x in obj.References[0][1]]
        for n in names:
            s = self._getBndSection(n)
            if not obj.xFree:
                s["Displacement 1"] = float(obj.xDisplacement) * 0.001
            elif obj.xFix:
                s["Displacement 1"] = 0.0
            if not obj.yFree:
                s["Displacement 2"] = float(obj.yDisplacement) * 0.001
            elif obj.yFix:
                s["Displacement 2"] = 0.0
            if not obj.zFree:
                s["Displacement 3"] = float(obj.zDisplacement) * 0.001
            elif obj.zFix:
                s["Displacement 3"] = 0.0

    def _createForces(self, obj):
        names = [self._getGroupName(x) for x in obj.References[0][1]]
        for n in names:
            s = self._getBndSection(n)
            s["Force 1"] = float(obj.DirectionVector.x * obj.Force)
            s["Force 2"] = float(obj.DirectionVector.y * obj.Force)
            s["Force 3"] = float(obj.DirectionVector.z * obj.Force)
            s["Force 1 Normalize by Area"] = True
            s["Force 2 Normalize by Area"] = True
            s["Force 3 Normalize by Area"] = True

    def _createTemps(self, obj):
        names = [self._getGroupName(x) for x in obj.References[0][1]]
        for n in names:
            s = self._getBndSection(n)
            s["Temperature"] = float(obj.Temperature)

    def _getInitialTemp(self, obj):
        s = sifio.createSection(sifio.INITIAL_CONDITION)
        s["Temperature"] = obj.initialTemperature
        return s

    def _getInUnit(self, value, unitStr):
        return float(Units.Quantity(value).getValueAs(unitStr))

    def _getBndSection(self, name):
        if name in self._bndSections:
            return self._bndSections[name]
        s = sifio.createSection(sifio.BOUNDARY_CONDITION)
        s["Name"] = name
        self._bndSections[name] = s
        return s
