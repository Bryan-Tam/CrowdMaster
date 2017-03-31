# Copyright 2017 CrowdMaster Developer Team
#
# ##### BEGIN GPL LICENSE BLOCK ######
# This file is part of CrowdMaster.
#
# CrowdMaster is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# CrowdMaster is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with CrowdMaster.  If not, see <http://www.gnu.org/licenses/>.
# ##### END GPL LICENSE BLOCK #####

import bpy
import mathutils
BVHTree = mathutils.bvhtree.BVHTree
KDTree = mathutils.kdtree.KDTree

from collections import OrderedDict

import random
import math
from math import radians

from ..libs.ins_vector import Vector
from ..libs.ins_octree import createOctreeFromBPYObjs

# ==================== Some base classes ====================


class Template():
    """Abstract super class.
    Templates are a description of how to create some arrangement of agents"""
    def __init__(self, inputs, settings, bpyName):
        """":param input: A list of Templates or GeoTemplates generated by the
        nodes that are connected to inputs of this node"""
        self.inputs = inputs
        self.bpyName = bpyName
        self.settings = settings

        self.buildCount = 0
        self.checkCache = None

    def build(self, buildRequest):
        """Called when this template is being used to modify the scene"""
        self.buildCount += 1

    def check(self):
        """Return true if the inputs and gettings are correct"""
        return True


class TemplateRequest():
    """Passed between the children of Template"""
    def __init__(self):
        self.pos = Vector((0, 0, 0))
        self.rot = Vector((0, 0, 0))
        self.scale = 1
        self.tags = {}
        self.cm_group = "cm_allAgents"

        self.materials = {}
        # Key: material to replace. Value: material to replace with

    def copy(self):
        new = TemplateRequest()
        new.pos = self.pos
        new.rot = self.rot
        new.scale = self.scale
        new.tags = self.tags.copy()
        new.cm_group = self.cm_group
        new.materials = self.materials.copy()
        return new

    def toGeoTemplate(self, deferGeo, group):
        new = GeoRequest()
        new.pos = self.pos
        new.rot = self.rot
        new.scale = self.scale
        new.tags = self.tags.copy()
        new.cm_group = self.cm_group
        new.group = group
        new.materials = self.materials.copy()
        new.deferGeo = deferGeo
        return new


class GeoTemplate(Template):
    """Abstract super class.
    GeoTemplates are a description of how to create some arrangement of
     geometry"""
    def build(self, pos, rot, scale, group, deferGeo):
        """Called when this GeoTemplate is being used to modify the scene"""
        self.buildCount += 1


class GeoRequest(TemplateRequest):
    """Passed between the children of GeoTemplate"""
    def __init__(self):
        TemplateRequest.__init__(self)
        self.deferGeo = False
        self.group = None

    def copy(self):
        new = GeoRequest()
        new.pos = self.pos
        new.rot = self.rot
        new.scale = self.scale
        new.tags = self.tags.copy()
        new.cm_group = self.cm_group
        new.group = self.group
        new.materials = self.materials.copy()
        new.deferGeo = self.deferGeo
        return new


# ==================== End of base classes ====================


class GeoTemplateOBJECT(GeoTemplate):
    """For placing objects into the scene"""
    def build(self, buildRequest):
        obj = bpy.context.scene.objects[self.settings["inputObject"]]
        if buildRequest.deferGeo:
            cp = bpy.data.objects.new("Empty", None)
            cp.matrix_world = obj.matrix_world
            cp["cm_deferObj"] = obj.name
            cp["cm_materials"] = buildRequest.materials
        else:
            cp = obj.copy()
            for m in cp.material_slots:
                if m.name in buildRequest.materials:
                    replacement = buildRequest.materials[m.name]
                    m.material = bpy.data.materials[replacement]
        buildRequest.group.objects.link(cp)
        bpy.context.scene.objects.link(cp)
        return cp

    def check(self):
        return self.settings["inputObject"] in bpy.context.scene.objects


class GeoTemplateGROUP(GeoTemplate):
    """For placing groups into the scene"""
    def build(self, buildRequest):
        dat = bpy.data

        pos = buildRequest.pos
        rot = buildRequest.rot
        scale = buildRequest.scale
        group = buildRequest.group
        deferGeo = buildRequest.deferGeo

        gp = [o for o in dat.groups[self.settings["inputGroup"]].objects]
        group_objects = [o.copy() for o in gp]
        zaxis = lambda x: x.location[2]

        if deferGeo:
            for obj in dat.groups[self.settings["inputGroup"]].objects:
                if obj.type == 'ARMATURE':
                    newObj = obj.copy()
                    newObj.rotation_euler = rot
                    newObj.scale = Vector((scale, scale, scale))
                    newObj.location = pos
                    group.objects.link(newObj)
                    bpy.context.scene.objects.link(newObj)
                    newObj["cm_deferGroup"] = {"group": self.settings["inputGroup"],
                                               "aName": obj.name}
                    newObj["cm_materials"] = buildRequest.materials
                    return newObj
            bpy.ops.object.add(type='EMPTY',
                               location=min(group_objects, key=zaxis).location)
            e = bpy.context.object
            group.objects.link(e)
            e["cm_deferGroup"] = {"group": self.settings["inputGroup"]}
            e["cm_materials"] = buildRequest.materials
            return e

        topObj = None

        for obj in group_objects:
            for m in obj.material_slots:
                if m.name in buildRequest.materials:
                    replacement = buildRequest.materials[m.name]
                    m.material = bpy.data.materials[replacement]

            if obj.parent in gp:
                obj.parent = group_objects[gp.index(obj.parent)]
            else:
                obj.rotation_euler = Vector(obj.rotation_euler) + rot
                obj.scale = Vector((scale, scale, scale))
                obj.location += pos

            group.objects.link(obj)
            bpy.context.scene.objects.link(obj)
            if obj.type == 'ARMATURE':
                aName = obj.name
                # TODO what if there is more than one armature?
            if obj.type == 'MESH':
                if len(obj.modifiers) > 0:
                    for mod in obj.modifiers:
                        if mod.type == "ARMATURE":
                            modName = mod.name
                            obj.modifiers[modName].object = dat.objects[aName]

            if obj.type == 'ARMATURE':
                topObj = obj

        if topObj is None:  # For if there is no armature object in the group
            bpy.ops.object.add(type='EMPTY',
                               location=min(group_objects, key=zaxis).location)
            e = bpy.context.object
            group.objects.link(e)
            for obj in group_objects:
                if obj.parent not in group_objects:
                    obj.location -= pos
                    obj.parent = e
            topObj = e
        return topObj

    def check(self):
        return self.settings["inputGroup"] in bpy.data.groups


class GeoTemplateSWITCH(GeoTemplate):
    """Randomly (biased by "switchAmout") pick which of the inputs to use"""
    def build(self, buildRequest):
        if random.random() < self.settings["switchAmout"]:
            return self.inputs["Object 1"].build(buildRequest)
        else:
            return self.inputs["Object 2"].build(buildRequest)

    def check(self):
        if "Object 1" not in self.inputs:
            return False
        if "Object 2" not in self.inputs:
            return False
        if not isinstance(self.inputs["Object 1"], GeoTemplate):
            return False
        if not isinstance(self.inputs["Object 2"], GeoTemplate):
            return False
        return True


class GeoTemplatePARENT(GeoTemplate):
    """Attach a piece of geo to a bone from the parent geo"""
    def build(self, buildRequest):
        parent = self.inputs["Parent Group"].build(buildRequest.copy())
        child = self.inputs["Child Object"].build(buildRequest.copy())
        con = child.constraints.new("CHILD_OF")
        con.target = parent
        con.subtarget = self.settings["parentTo"]
        bone = parent.pose.bones[self.settings["parentTo"]]
        con.inverse_matrix = bone.matrix.inverted()
        if child.data:
            child.data.update()
        return parent
        # TODO check if the object has an armature modifier

    def check(self):
        if "Parent Group" not in self.inputs:
            return False
        if "Child Object" not in self.inputs:
            return False
        if not isinstance(self.inputs["Parent Group"], GeoTemplate):
            return False
        if not isinstance(self.inputs["Child Object"], GeoTemplate):
            return False
        # TODO check that object is in parent group
        return True


class TemplateADDTOGROUP(Template):
    """Change the group that agents are added to"""
    def build(self, buildRequest):
        scene = bpy.context.scene
        isFrozen = False
        if scene.cm_groups.find(self.settings["groupName"]) != -1:
            group = scene.cm_groups[self.settings["groupName"]]
            isFrozen = group.freezePlacement
            if group.groupType == "auto":
                bpy.ops.scene.cm_groups_reset(groupName=self.settings["groupName"])
            else:
                return
        if isFrozen:
            return
        newGroup = scene.cm_groups.add()
        newGroup.name = self.settings["groupName"]
        buildRequest.cm_groups = self.settings["groupName"]
        self.inputs["Template"].build(buildRequest)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        if self.settings["groupName"].strip() == "":
            return False
        return True


class TemplateRANDOMMATERIAL(Template):
    """Assign random materials"""
    def build(self, buildRequest):
        s = random.random() * self.settings["totalWeight"]
        index = 0
        mat = None
        while mat is None:
            s -= self.settings["materialList"][index][1]
            if s <= 0:
                mat = self.settings["materialList"][index][0]
            index += 1
        buildRequest.materials[self.settings["targetMaterial"]] = mat
        self.inputs["Template"].build(buildRequest)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        return True


class TemplateAGENT(Template):
    """Create a CrowdMaster agent"""
    def build(self, buildRequest):
        groupName = buildRequest.cm_group + "/" + self.settings["brainType"]
        newGp = bpy.data.groups.new(groupName)
        defG = self.settings["deferGeo"]
        pos = buildRequest.pos
        rot = buildRequest.rot
        scale = buildRequest.scale
        geoBuildRequest = buildRequest.toGeoTemplate(defG, newGp)
        topObj = self.inputs["Objects"].build(geoBuildRequest)
        topObj.location = pos
        topObj.rotation_euler = rot
        topObj.scale = Vector((scale, scale, scale))

        topObj["cm_randomMaterial"] = buildRequest.materials

        tags = buildRequest.tags
        packTags = [{"name": x, "value": tags[x]} for x in tags]
        bpy.ops.scene.cm_agent_add(agentName=topObj.name,
                                   brainType=self.settings["brainType"],
                                   groupName=buildRequest.cm_group,
                                   geoGroupName=newGp.name,
                                   initialTags=packTags)

    def check(self):
        if "Objects" not in self.inputs:
            return False
        if not isinstance(self.inputs["Objects"], GeoTemplate):
            return False
        return True


class TemplateSWITCH(Template):
    """Randomly (biased by "switchAmout") pick which of the inputs to use"""
    def build(self, buildRequest):
        if random.random() < self.settings["switchAmout"]:
            self.inputs["Template 1"].build(buildRequest)
        else:
            self.inputs["Template 2"].build(buildRequest)

    def check(self):
        if "Template 1" not in self.inputs:
            return False
        if "Template 2" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template 1"], Template):
            return False
        if isinstance(self.inputs["Template 1"], GeoTemplate):
            return False
        if not isinstance(self.inputs["Template 2"], Template):
            return False
        if isinstance(self.inputs["Template 2"], GeoTemplate):
            return False
        return True


class TemplateOFFSET(Template):
    """Modify the postion and/or the rotation of the request made"""
    def build(self, buildRequest):
        nPos = Vector()
        nRot = Vector()
        if not self.settings["overwrite"]:
            nPos = Vector(buildRequest.pos)
            nRot = Vector(buildRequest.rot)
        if self.settings["referenceObject"] != "":
            refObj = bpy.data.objects[self.settings["referenceObject"]]
            nPos += refObj.location
            nRot += Vector(refObj.rotation_euler)
        nPos += self.settings["locationOffset"]
        tmpRot = self.settings["rotationOffset"]
        nRot += Vector((radians(tmpRot.x), radians(tmpRot.y), radians(tmpRot.z)))
        buildRequest.pos = nPos
        buildRequest.rot = nRot
        self.inputs["Template"].build(buildRequest)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        ref = self.settings["referenceObject"]
        if ref != "" and ref not in bpy.context.scene.objects:
            return False
        return True


class TemplateRANDOM(Template):
    """Randomly modify rotation and scale of the request made"""
    def build(self, buildRequest):
        rotDiff = random.uniform(self.settings["minRandRot"],
                                 self.settings["maxRandRot"])
        eul = mathutils.Euler(buildRequest.rot, 'XYZ')
        eul.rotate_axis('Z', math.radians(rotDiff))

        scaleDiff = random.uniform(self.settings["minRandSz"],
                                   self.settings["maxRandSz"])
        newScale = buildRequest.scale * scaleDiff

        buildRequest.rot = Vector(eul)
        buildRequest.scale = newScale
        self.inputs["Template"].build(buildRequest)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        return True


class TemplatePOINTTOWARDS(Template):
    """Rotate to point towards object or closest point on mesh"""
    def __init__(self, inputs, settings, bpyName):
        Template.__init__(self, inputs, settings, bpyName)
        self.kdtree = None

    def build(self, buildRequest):
        ob = bpy.context.scene.objects[self.settings["PointObject"]]
        pos = buildRequest.pos
        if self.settings["PointType"] == "OBJECT":
            point = ob.location
        else:  # self.settings["PointObject"] == "MESH":
            if self.kdtree is None:
                mesh = ob.data
                self.kdtree = KDTree(len(mesh.vertices))
                for i, v in enumerate(mesh.vertices):
                    self.kdtree.insert(v.co, i)
                self.kdtree.balance()
            co, ind, dist = self.kdtree.find(ob.matrix_world.inverted() * pos)
            point = ob.matrix_world * co
        direc = point - pos
        rotQuat = direc.to_track_quat('Y', 'Z')
        buildRequest.rot = rotQuat.to_euler()
        self.inputs["Template"].build(buildRequest)

    def check(self):
        if self.settings["PointObject"] not in bpy.context.scene.objects:
            return False
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        return True



class TemplateCOMBINE(Template):
    """Duplicate request to all inputs"""
    def build(self, buildRequest):
        for name, inp in self.inputs.items():
            newBuildRequest = buildRequest.copy()
            inp.build(newBuildRequest)


class TemplateRANDOMPOSITIONING(Template):
    """Place randomly"""
    def build(self, buildRequest):
        positions = []
        for a in range(self.settings["noToPlace"]):
            if self.settings["locationType"] == "radius":
                angle = random.uniform(-math.pi, math.pi)
                x = math.sin(angle)
                y = math.cos(angle)
                length = random.random() + random.random()
                if length > 1:
                    length = 2 - length
                length *= self.settings["radius"]
                x *= length
                y *= length
                diff = Vector((x, y, 0))
                diff.rotate(mathutils.Euler(buildRequest.rot))
                newPos = Vector(buildRequest.pos) + diff
                positions.append(newPos)
            elif self.settings["locationType"] == "area":
                MaxX = self.settings["MaxX"]/2
                MaxY = self.settings["MaxY"]/2
                x = random.uniform(-MaxX, MaxX)
                y = random.uniform(-MaxY, MaxY)
                diff = Vector((x, y, 0))
                newPos = Vector(buildRequest.pos) + diff
                positions.append(newPos)
            elif self.settings["locationType"] == "sector":
                direc = self.settings["direc"]
                angVar = self.settings["angle"]/2
                angle = random.uniform(-angVar, angVar)
                x = math.sin(math.radians(angle + direc))
                y = math.cos(math.radians(angle + direc))
                length = random.random() + random.random()
                if length > 1:
                    length = 2 - length
                length *= self.settings["radius"]
                x *= length
                y *= length
                diff = Vector((x, y, 0))
                diff.rotate(mathutils.Euler(buildRequest.rot))
                newPos = Vector(buildRequest.pos) + diff
                positions.append(newPos)
        if self.settings["relax"]:
            radius = self.settings["relaxRadius"]
            for i in range(self.settings["relaxIterations"]):
                kd = KDTree(len(positions))
                for n, p in enumerate(positions):
                    kd.insert(p, n)
                kd.balance()
                for n, p in enumerate(positions):
                    adjust = Vector()
                    localPoints = kd.find_range(p, radius*2)
                    for (co, ind, dist) in localPoints:
                        if ind != n:
                            v = p - co
                            adjust += v * ((2*radius - v.length)/v.length)
                    if len(localPoints) > 0:
                        positions[n] += adjust/len(localPoints)
        for newPos in positions:
            newBuildRequest = buildRequest.copy()
            newBuildRequest.pos = newPos
            self.inputs["Template"].build(newBuildRequest)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        return True


class TemplateFORMATION(Template):
    """Place in a row"""
    def build(self, buildRequest):
        placePos = Vector(buildRequest.pos)
        diffRow = Vector((self.settings["ArrayRowMargin"], 0, 0))
        diffCol = Vector((0, self.settings["ArrayColumnMargin"], 0))
        diffRow.rotate(mathutils.Euler(buildRequest.rot))
        diffCol.rotate(mathutils.Euler(buildRequest.rot))
        diffRow *= buildRequest.scale
        diffCol *= buildRequest.scale
        number = self.settings["noToPlace"]
        rows = self.settings["ArrayRows"]
        for fullcols in range(number // rows):
            for row in range(rows):
                newBuildRequest = buildRequest.copy()
                newBuildRequest.pos = placePos + fullcols*diffCol + row*diffRow
                self.inputs["Template"].build(newBuildRequest)
        for leftOver in range(number % rows):
            newBuild = buildRequest.copy()
            newBuild.pos = placePos + (number//rows)*diffCol + leftOver*diffRow
            self.inputs["Template"].build(newBuild)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        return True


class TemplateTARGET(Template):
    """Place based on the positions of vertices"""
    def build(self, buildRequest):
        if self.settings["targetType"] == "object":
            objs = bpy.data.groups[self.settings["targetGroups"]].objects
            if self.settings["overwritePosition"]:
                for obj in objs:
                    newBuildRequest = buildRequest.copy()
                    newBuildRequest.pos = obj.location
                    newBuildRequest.rot = Vector(obj.rotation_euler)
                    self.inputs["Template"].build(newBuildRequest)
            else:
                for obj in objs:
                    loc = obj.location
                    oRot = Vector(obj.rotation_euler)
                    loc.rotate(mathutils.Euler(rot))
                    loc *= scale
                    newBuildRequest = buildRequest.copy()
                    newBuildRequest.pos = loc + buildRequest.pos
                    newBuildRequest.rot = buildRequest.rot + oRot
                    self.inputs["Template"].build(newBuildRequest)
        else:  # targetType == "vertex"
            obj = bpy.data.objects[self.settings["targetObject"]]
            if self.settings["overwritePosition"]:
                wrld = obj.matrix_world
                targets = [wrld*v.co for v in obj.data.vertices]
                newRot = Vector(obj.rotation_euler)
                for vert in targets:
                    newBuildRequest = buildRequest.copy()
                    newBuildRequest.pos = vert
                    newBuildRequest.rot = newRot
                    self.inputs["Template"].build(newBuildRequest)
            else:
                targets = [Vector(v.co) for v in obj.data.vertices]
                for loc in targets:
                    loc.rotate(mathutils.Euler(buildRequest.rot))
                    loc *= buildRequest.scale
                    newBuildRequest = buildRequest.copy()
                    newBuildRequest.pos = loc + buildRequest.pos
                    self.inputs["Template"].build(newBuildRequest)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        if self.settings["targetType"] == "object":
            if self.settings["targetGroups"] not in bpy.data.groups:
                return False
        elif self.settings["targetType"] == "vertex":
            if self.settings["targetObject"] not in bpy.context.scene.objects:
                return False
        return True


class TemplateOBSTACLE(Template):
    """Refuse any requests that are withing the bounding box of an obstacle"""
    def __init__(self, inputs, settings, bpyName):
        Template.__init__(self, inputs, settings, bpyName)
        self.octree = None

    def build(self, buildRequest):
        if self.octree is None:
            objs = bpy.data.groups[self.settings["obstacleGroup"]].objects
            margin = self.settings["margin"]
            mVec = Vector((margin, margin, margin))
            radii = [(o.dimensions/2) + mVec for o in objs]
            self.octree = createOctreeFromBPYObjs(objs, allSpheres=False,
                                                  radii=radii)
        intersections = self.octree.checkPoint(buildRequest.pos)
        if len(intersections) == 0:
            self.inputs["Template"].build(buildRequest)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        if self.settings["obstacleGroup"] not in bpy.data.groups:
            return False
        return True


class TemplateGROUND(Template):
    """Adjust the position of requests onto a ground mesh"""
    def __init__(self, inputs, settings, bpyName):
        Template.__init__(self, inputs, settings, bpyName)
        self.bvhtree = None

    def build(self, buildRequest):
        sce = bpy.context.scene
        gnd = sce.objects[self.settings["groundMesh"]]
        if self.bvhtree is None:
            self.bvhtree = BVHTree.FromObject(gnd, sce)
        point = buildRequest.pos - gnd.location
        hitA, normA, indA, distA = self.bvhtree.ray_cast(point, (0, 0, -1))
        hitB, normB, indB, distB = self.bvhtree.ray_cast(point, (0, 0, 1))
        if hitA and hitB:
            if distA <= distB:
                hitA += gnd.location
                buildRequest.pos = hitA
                self.inputs["Template"].build(buildRequest)
            else:
                hitB += gnd.location
                buildRequest.pos = hitB
                self.inputs["Template"].build(buildRequest)
        elif hitA:
            hitA += gnd.location
            buildRequest.pos = hitA
            self.inputs["Template"].build(buildRequest)
        elif hitB:
            hitB += gnd.location
            buildRequest.pos = hitB
            self.inputs["Template"].build(buildRequest)

    def check(self):
        if self.settings["groundMesh"] not in bpy.context.scene.objects:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        return True


class TemplateSETTAG(Template):
    """Set a tag for an agent to start with"""
    def build(self, buildRequest):
        buildRequest.tags[self.settings["tagName"]] = self.settings["tagValue"]
        self.inputs["Template"].build(buildRequest)

    def check(self):
        if "Template" not in self.inputs:
            return False
        if not isinstance(self.inputs["Template"], Template):
            return False
        if isinstance(self.inputs["Template"], GeoTemplate):
            return False
        return True

templates = OrderedDict([
    ("ObjectInputNodeType", GeoTemplateOBJECT),
    ("GroupInputNodeType", GeoTemplateGROUP),
    ("GeoSwitchNodeType", GeoTemplateSWITCH),
    ("AddToGroupNodeType", TemplateADDTOGROUP),
    ("TemplateSwitchNodeType", TemplateSWITCH),
    ("ParentNodeType", GeoTemplatePARENT),
    ("RandomMaterialNodeType", TemplateRANDOMMATERIAL),
    ("TemplateNodeType", TemplateAGENT),
    ("OffsetNodeType", TemplateOFFSET),
    ("RandomNodeType", TemplateRANDOM),
    ("PointTowardsNodeType", TemplatePOINTTOWARDS),
    ("CombineNodeType", TemplateCOMBINE),
    ("RandomPositionNodeType", TemplateRANDOMPOSITIONING),
    ("FormationPositionNodeType", TemplateFORMATION),
    ("TargetPositionNodeType", TemplateTARGET),
    ("ObstacleNodeType", TemplateOBSTACLE),
    ("GroundNodeType", TemplateGROUND),
    ("SettagNodeType", TemplateSETTAG)
])
