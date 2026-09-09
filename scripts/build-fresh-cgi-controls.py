#!/usr/bin/env python3
"""Render two frozen conventional-CGI controls. No detector or network calls.

Run with the project's Python; it invokes pinned Blender in background CPU mode.
The same script is copied into the attempt directory and used inside Blender.
Geometry, materials, lighting, motion, and encoding are entirely code-defined.
"""
from __future__ import annotations

import bisect
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

PLAN_HASH = "2cd6b58d8f368d49123f3d71f78c6ceebe0b2b0a58e5bc5b66bfd6bde662e888"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while b := f.read(1024 * 1024):
            h.update(b)
    return h.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def rk4(q, v, dt, acceleration):
    a1 = acceleration(q, v)
    q2, v2 = q + dt * v / 2, v + dt * a1 / 2
    a2 = acceleration(q2, v2)
    q3, v3 = q + dt * v2 / 2, v + dt * a2 / 2
    a3 = acceleration(q3, v3)
    q4, v4 = q + dt * v3, v + dt * a3
    a4 = acceleration(q4, v4)
    return q + dt * (v + 2*v2 + 2*v3 + v4) / 6, v + dt * (a1 + 2*a2 + 2*a3 + a4) / 6


def blender_worker(plan_path, scene_id, directory):
    import bpy
    from mathutils import Vector

    plan = json.loads(Path(plan_path).read_text())
    assert digest(plan_path) == PLAN_HASH
    assert bpy.app.version_string == plan["blenderVersion"]
    assert bpy.app.build_hash.decode() == plan["blenderBuildHash"]
    spec = next(s for s in plan["scenes"] if s["id"] == scene_id)
    directory = Path(directory)
    frames = directory / "frames"
    frames.mkdir(exist_ok=False)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = plan["renderSamples"]
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_animated_seed = False
    scene.cycles.seed = spec["seed"]
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 2
    scene.cycles.glossy_bounces = 2
    scene.cycles.transmission_bounces = 2
    scene.cycles.transparent_max_bounces = 2
    scene.render.threads_mode = "FIXED"
    scene.render.threads = plan["cpuThreads"]
    scene.render.use_persistent_data = True
    scene.render.resolution_x = plan["width"]
    scene.render.resolution_y = plan["height"]
    scene.render.resolution_percentage = 100
    scene.render.fps = plan["fps"]
    scene.render.fps_base = 1
    scene.render.film_transparent = False
    scene.render.use_motion_blur = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.frame_start, scene.frame_end = 1, 192
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.14, 0.18, 0.24, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.28

    def material(name, color, metallic=0, roughness=0.4):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        node = m.node_tree.nodes.get("Principled BSDF")
        node.inputs["Base Color"].default_value = (*color, 1)
        node.inputs["Metallic"].default_value = metallic
        node.inputs["Roughness"].default_value = roughness
        return m

    floor_mat = material("Warm gray studio floor", (0.16, 0.17, 0.18), 0, 0.65)
    metal = material("Graphite powder-coated metal", (0.025, 0.035, 0.048), 0.65, 0.29)
    brass = material("Satin brass", (0.58, 0.30, 0.075), 0.85, 0.22)
    steel = material("Brushed steel", (0.36, 0.42, 0.49), 0.9, 0.26)
    wood = material("Solid warm ramp finish", (0.25, 0.074, 0.026), 0, 0.39)
    blue = material("Blue ceramic enamel", (0.022, 0.105, 0.27), 0.22, 0.2)

    def cube(name, location, dimensions, mat, bevel=0.04):
        bpy.ops.mesh.primitive_cube_add(size=1, location=location)
        o = bpy.context.object
        o.name = name
        o.dimensions = dimensions
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        o.data.materials.append(mat)
        if bevel:
            modifier = o.modifiers.new("Machined edge radius", "BEVEL")
            modifier.width = bevel
            modifier.segments = 3
        return o

    def cylinder(name, start, end, radius, mat, vertices=40):
        start, end = Vector(start), Vector(end)
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=(end-start).length, location=(start+end)/2)
        o = bpy.context.object
        o.name = name
        o.rotation_mode = "QUATERNION"
        o.rotation_quaternion = (end-start).to_track_quat("Z", "Y")
        o.data.materials.append(mat)
        for polygon in o.data.polygons:
            polygon.use_smooth = len(polygon.vertices) == 4
        return o

    def sphere(name, position, radius, mat):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=radius, location=position)
        o = bpy.context.object
        o.name = name
        o.data.materials.append(mat)
        for polygon in o.data.polygons:
            polygon.use_smooth = True
        return o

    def area(name, position, target, energy, size, color):
        light = bpy.data.lights.new(name, "AREA")
        light.energy, light.shape, light.size = energy, "DISK", size
        light.color = color
        o = bpy.data.objects.new(name, light)
        scene.collection.objects.link(o)
        o.location = position
        o.rotation_euler = (Vector(target)-o.location).to_track_quat("-Z", "Y").to_euler()

    cube("Studio ground", (0, 0, -0.18), (24, 24, 0.2), floor_mat, 0)
    area("Large warm key", (-3.5, -4.5, 7), (0, 0, 1.5), 1350, 5, (1.0, 0.89, 0.74))
    area("Cool soft fill", (4, -1, 4.5), (0, 0, 1.4), 900, 4, (0.64, 0.78, 1.0))
    area("Upper rim light", (0, 4, 6.5), (0, 0, 1.8), 1600, 4, (1.0, 0.91, 0.78))
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = "Fixed perspective camera"
    camera.data.lens = 46
    camera.data.clip_start, camera.data.clip_end = 0.1, 100
    scene.camera = camera
    motion = []

    if scene_id == "fresh-cgi-pendulum-v1":
        cube("Beveled stone pedestal", (0, 0.25, 0.01), (5.4, 2.5, 0.18), metal, 0.08)
        for x in (-2.0, 2.0):
            cube(f"Support column {x}", (x, 0.35, 2.1), (0.2, 0.32, 4.0), metal)
            cube(f"Column foot {x}", (x, 0.35, 0.16), (0.72, 0.85, 0.18), steel)
        cube("Upper support beam", (0, 0.35, 4.1), (4.3, 0.35, 0.22), metal)
        cylinder("Pivot axle", (0, -0.22, 3.86), (0, 0.62, 3.86), 0.13, brass)
        pivot = bpy.data.objects.new("Animated pendulum pivot", None)
        scene.collection.objects.link(pivot)
        pivot.location = (0, -0.15, 3.86)
        rod = cylinder("Pendulum steel rod", (0, 0, -0.02), (0, 0, -2.6), 0.037, steel)
        bob = sphere("Brass pendulum bob", (0, 0, -2.6), 0.38, brass)
        rod.parent = pivot
        bob.parent = pivot
        q, v = 0.48, 0.0
        acceleration = lambda angle, velocity: -(9.81 / 2.6) * math.sin(angle) - 0.025 * velocity
        for frame in range(1, 193):
            pivot.rotation_euler = (0, q, 0)
            pivot.keyframe_insert(data_path="rotation_euler", frame=frame)
            motion.append({"frame": frame, "seconds": (frame-1)/24, "angleRadians": q, "angularVelocity": v})
            for _ in range(8):
                q, v = rk4(q, v, 1/192, acceleration)
        camera.location = (7.4, -10.5, 6.0)
        target = Vector((0, 0.15, 2.05))
    else:
        surface_x = [-3 + 6*i/160 for i in range(161)]
        top = lambda x: 0.35 + 0.2*x*x
        vertices = [(x,y,top(x)-thickness) for x in surface_x for y,thickness in [(-0.82,0),(0.82,0),(-0.82,0.18),(0.82,0.18)]]
        faces = []
        for i in range(len(surface_x)-1):
            a, b = 4*i, 4*(i+1)
            faces.extend([(a,b,b+1,a+1),(a+2,a+3,b+3,b+2),(a,a+2,b+2,b),(a+1,b+1,b+3,a+3)])
        faces.extend([(0,1,3,2),(640,642,643,641)])
        mesh = bpy.data.meshes.new("Curved solid ramp mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        ramp = bpy.data.objects.new("Curved wooden ramp", mesh)
        scene.collection.objects.link(ramp)
        ramp.data.materials.append(wood)
        for y in (-0.8, 0.8):
            curve = bpy.data.curves.new(f"Ramp edge rail {y}", "CURVE")
            curve.dimensions = "3D"
            curve.bevel_depth, curve.bevel_resolution = 0.035, 3
            spline = curve.splines.new("POLY")
            spline.points.add(len(surface_x)-1)
            for point,x in zip(spline.points,surface_x):
                point.co = (x,y,top(x)+0.015,1)
            rail = bpy.data.objects.new(curve.name, curve)
            scene.collection.objects.link(rail)
            rail.data.materials.append(brass)
        for x in (-2.5, 0, 2.5):
            height = top(x) - 0.18
            cube(f"Ramp support {x}", (x,0,(height-0.06)/2), (0.26,1.25,height+0.06), metal)
            cube(f"Support foot {x}", (x,0,-0.045), (0.75,1.65,0.08), steel)

        radius = 0.38
        ball = sphere("Rolling blue sphere with brass meridians", (0,0,1), radius, blue)
        ball.data.materials.append(brass)
        for polygon in ball.data.polygons:
            center = sum((ball.data.vertices[i].co for i in polygon.vertices), Vector()) / len(polygon.vertices)
            longitude = math.atan2(center.y,center.x)
            if abs(math.sin(2*longitude)) < 0.25:
                polygon.material_index = 1
        xs = [-3 + 6*i/2000 for i in range(2001)]
        center_points=[]
        for x in xs:
            slope=0.4*x
            normal=math.sqrt(1+slope*slope)
            center_points.append((x-radius*slope/normal,top(x)+radius/normal))
        arc=[0.0]
        for a,b in zip(center_points,center_points[1:]):
            arc.append(arc[-1]+math.hypot(b[0]-a[0],b[1]-a[1]))
        def interpolate(s):
            index=max(0,min(len(arc)-2,bisect.bisect_right(arc,s)-1))
            f=(s-arc[index])/(arc[index+1]-arc[index])
            a,b=center_points[index:index+2]
            return (a[0]+f*(b[0]-a[0]), a[1]+f*(b[1]-a[1]), (b[1]-a[1])/(arc[index+1]-arc[index]))
        start_index=bisect.bisect_right(xs,-2.6)-1
        fraction=(-2.6-xs[start_index])/(xs[start_index+1]-xs[start_index])
        q=arc[start_index]+fraction*(arc[start_index+1]-arc[start_index])
        origin=q
        v=0.0
        acceleration=lambda s,velocity: -(5/7)*9.81*interpolate(s)[2]-0.018*velocity
        for frame in range(1,193):
            assert arc[0] <= q <= arc[-1]
            x,z,slope=interpolate(q)
            angle=(q-origin)/radius
            ball.location=(x,0,z)
            ball.rotation_euler=(0,angle,0)
            ball.keyframe_insert(data_path="location",frame=frame)
            ball.keyframe_insert(data_path="rotation_euler",frame=frame)
            motion.append({"frame":frame,"seconds":(frame-1)/24,"location":[x,0,z],"arcPosition":q,"speed":v,"rollRadians":angle})
            for _ in range(8):
                q,v=rk4(q,v,1/192,acceleration)
        camera.location=(7.2,-9.5,6.0)
        target=Vector((0,0,1.0))

    camera.rotation_euler=(target-camera.location).to_track_quat("-Z","Y").to_euler()
    scene.frame_set(1)
    scene["origin"] = plan["origin"]
    scene["content_plan_sha256"] = PLAN_HASH
    scene["parent_id"] = scene_id
    scene["motion_description"] = spec["motion"]
    scene["keyframe_policy"] = "Exact pose inserted at every output frame; default interpolation between frames; motion blur disabled."
    write_json(directory/"motion-keyframes.json",motion)
    bpy.ops.wm.save_as_mainfile(filepath=str(directory/"scene.blend"))
    source_receipt={"parentId":scene_id,"planSha256":PLAN_HASH,"blenderVersion":bpy.app.version_string,"buildHash":bpy.app.build_hash.decode(),"engine":scene.render.engine,"device":scene.cycles.device,"threads":scene.render.threads,"samples":scene.cycles.samples,"seed":scene.cycles.seed,"denoising":scene.cycles.use_denoising,"adaptiveSampling":scene.cycles.use_adaptive_sampling,"motionBlur":scene.render.use_motion_blur,"resolution":[scene.render.resolution_x,scene.render.resolution_y],"fps":scene.render.fps,"frames":[scene.frame_start,scene.frame_end],"worldStrength":scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value,"objects":len(scene.objects),"meshObjects":sum(o.type=="MESH" for o in scene.objects),"externalImages":[i.filepath for i in bpy.data.images if i.filepath],"externalLibraries":list(bpy.data.libraries.keys()),"motion":spec["motion"],"blendSha256":digest(directory/"scene.blend"),"motionKeyframesSha256":digest(directory/"motion-keyframes.json")}
    assert source_receipt["externalImages"] == [] and source_receipt["externalLibraries"] == []
    write_json(directory/"scene-receipt.json",source_receipt)
    started=time.monotonic()
    for frame in range(1,193):
        scene.frame_set(frame)
        scene.render.filepath=str(frames/f"frame-{frame:06d}.png")
        bpy.ops.render.render(write_still=True)
        if frame == 1 or frame % 12 == 0:
            write_json(directory/"render-progress.json",{"lastFrame":frame,"elapsedSeconds":time.monotonic()-started})
    write_json(directory/"render-complete.json",{"frames":192,"elapsedSeconds":time.monotonic()-started})


def main():
    root=Path(__file__).resolve().parents[1]
    media=root/"eval/media/fresh-cgi"
    plan_path=media/"content-plan.json"
    assert digest(plan_path) == PLAN_HASH
    plan=json.loads(plan_path.read_text())
    receipt_path=root/"eval/sources/fresh-cgi-render-receipt.json"
    if receipt_path.exists() or (media/"attempt-01").exists():
        raise ValueError("Existing attempts are immutable; refuse automatic rerender")
    attempt=media/"attempt-01"
    attempt.mkdir()
    script_copy=attempt/"build-fresh-cgi-controls.py"
    shutil.copyfile(__file__,script_copy)
    binary=Path(plan["blenderBinary"])
    version=subprocess.check_output([str(binary),"--version"],text=True,timeout=15)
    if not version.startswith("Blender "+plan["blenderVersion"]+"\n"):
        raise ValueError("Blender version drift")
    (attempt/"blender-version.txt").write_text(version)
    ffmpeg_version=subprocess.check_output(["ffmpeg","-version"],text=True,timeout=15)
    (attempt/"ffmpeg-version.txt").write_text(ffmpeg_version)
    receipt={"purpose":"Two independent new conventional-CGI control parents; no detector calls or mixing","startedAt":datetime.now(timezone.utc).isoformat(),"planPath":str(plan_path.relative_to(root)),"planSha256":PLAN_HASH,"scriptPath":str(Path(__file__).relative_to(root)),"scriptSha256":digest(__file__),"sourceSnapshot":str(script_copy.relative_to(root)),"blenderBinary":str(binary),"blenderBinarySha256":digest(binary),"blenderVersion":version.splitlines()[0],"ffmpegBinary":shutil.which("ffmpeg"),"ffmpegVersion":ffmpeg_version.splitlines()[0],"networkRequests":0,"detectorCalls":0,"generativePixelModelCalls":0,"assistantAuthoredSceneCode":True,"label":"conventional_cgi","records":[]}
    write_json(receipt_path,receipt)
    for spec in plan["scenes"]:
        directory=media/spec["directory"]
        directory.mkdir()
        cmd=[str(binary),"--background","--factory-startup","--threads",str(plan["cpuThreads"]),"--python-exit-code","1","--python",str(script_copy),"--","--blender-worker",str(plan_path),spec["id"],str(directory)]
        record={"parentId":spec["id"],"sceneDirectory":str(directory.relative_to(root)),"command":cmd,"seed":spec["seed"],"startedAt":datetime.now(timezone.utc).isoformat(),"maximumProcessSeconds":plan["maximumSceneProcessSeconds"]}
        receipt["records"].append(record)
        write_json(receipt_path,receipt)
        started=time.monotonic()
        try:
            with (directory/"blender.log").open("w") as log:
                result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=plan["maximumSceneProcessSeconds"])
            record["exitCode"]=result.returncode
            if result.returncode != 0:
                raise RuntimeError("Blender failed; preserve the complete attempt log and partial outputs")
            pngs=sorted((directory/"frames").glob("frame-*.png"))
            if len(pngs) != 192:
                raise ValueError("Expected exactly192 rendered frames")
            frame_receipt=[{"frame":i,"path":str(p.relative_to(root)),"sha256":digest(p),"bytes":p.stat().st_size} for i,p in enumerate(pngs,1)]
            write_json(directory/"rendered-frames.json",frame_receipt)
            target=directory/"parent.mp4"
            encode=["ffmpeg","-v","error","-nostdin","-framerate","24","-start_number","1","-i",str(directory/"frames/frame-%06d.png"),"-frames:v","192","-an","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-r","24","-fps_mode","cfr","-movflags","+faststart",str(target)]
            subprocess.run(encode,check=True,capture_output=True,timeout=120)
            probe=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_format","-show_streams","-of","json",str(target)],timeout=30))
            video=next(s for s in probe["streams"] if s["codec_type"]=="video")
            assert (video["width"],video["height"],video["avg_frame_rate"],int(video["nb_frames"])) == (640,360,"24/1",192)
            assert abs(float(probe["format"]["duration"])-8.0)<1e-6
            packet=json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_frames","-show_entries","frame=best_effort_timestamp_time","-of","json",str(target)],timeout=30))
            pts=[float(f["best_effort_timestamp_time"]) for f in packet["frames"]]
            assert len(pts)==192 and all(abs(t-i/24)<1e-6 for i,t in enumerate(pts))
            write_json(directory/"presentation-timestamps.json",pts)
            record.update({"success":True,"path":str(target.relative_to(root)),"sha256":digest(target),"bytes":target.stat().st_size,"probe":probe,"pts":{"count":192,"first":pts[0],"last":pts[-1],"expectedStep":"1/24","allMatch":True},"encodeCommand":encode,"blendPath":str((directory/"scene.blend").relative_to(root)),"blendSha256":digest(directory/"scene.blend"),"sceneReceiptPath":str((directory/"scene-receipt.json").relative_to(root)),"sceneReceiptSha256":digest(directory/"scene-receipt.json"),"motionKeyframesSha256":digest(directory/"motion-keyframes.json"),"renderedFramesReceiptSha256":digest(directory/"rendered-frames.json")})
        except Exception as error:
            record.update({"success":False,"errorType":type(error).__name__,"error":str(error)})
            raise
        finally:
            record["elapsedSeconds"]=time.monotonic()-started
            record["finishedAt"]=datetime.now(timezone.utc).isoformat()
            receipt["completed"]=sum(r.get("success",False) for r in receipt["records"])
            write_json(receipt_path,receipt)
        print(json.dumps({k:record.get(k) for k in ["parentId","success","path","sha256","elapsedSeconds"]}),flush=True)
    receipt["finishedAt"]=datetime.now(timezone.utc).isoformat()
    assert digest(script_copy)==receipt["scriptSha256"]==digest(__file__)
    assert digest(plan_path)==PLAN_HASH
    write_json(receipt_path,receipt)


if __name__ == "__main__":
    if "--blender-worker" in sys.argv:
        i=sys.argv.index("--blender-worker")
        blender_worker(*sys.argv[i+1:i+4])
    else:
        main()
