
from . import lab
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator, AddonPreferences, Panel, UIList, PropertyGroup, Action, Context, ShapeKey
from bpy.props import *
import bpy
from copy import copy
import re


bl_info = {
    "name": "Import Lipsync Label(.lab)",
    "description": "Import label data obtained from \"VOICEVOX\" and other sources to construct animations.",
    "author": "suyaki almond",
    "version": (0, 0, 2),
    "blender": (3, 3, 0),
    "location": "View3D > Add > Mesh",
    "warning": "開発中",
    "doc_url": "",
    "tracker_url": "",
    "support": "TESTING",
    "category": "Animation"
}

if "bpy" in locals():
    import importlib
    if "lab" in locals():
        importlib.reload(lab)


class IMPLAB_MT_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    ui_dopesheet = BoolProperty(name="Display to Dope Sheet",
                                description="Display on side panel of Dope Sheet", default=True)
    ui_nlaeditor = BoolProperty(name="Display to LNA Editor",
                                description="Display on side panel of LNA Editor", default=True)


class ImplabActionPointer(PropertyGroup):
    viseme: StringProperty()
    pose: PointerProperty(type=Action)


class ImplabPropertyGroup(PropertyGroup):
    insert_frame: IntProperty(
        name="挿入フレーム",
        description="発音モーションを挿入するフレーム",
        default=1,
    )
    vowel_list: CollectionProperty(type=ImplabActionPointer)
    consonants_list: CollectionProperty(type=ImplabActionPointer)
    vowel_active_index: IntProperty("Active Index")
    consonants_active_index: IntProperty("Active Index")


def getShapeKeyList(self, context: Context):
    obj = context.active_object
    if obj.type != 'MESH':
        return []
    return [(item.name, item.name, "") for item in obj.data.shape_keys.key_blocks]


class ImplabShapekeyPointer(PropertyGroup):
    viseme: StringProperty()
    pose: EnumProperty(items=getShapeKeyList)


class ImplabMeshPropertyGroup(PropertyGroup):
    insert_frame: IntProperty(
        name="挿入フレーム",
        description="発音モーションを挿入するフレーム",
        default=1,
    )
    vowel_list: CollectionProperty(type=ImplabShapekeyPointer)
    consonants_list: CollectionProperty(type=ImplabShapekeyPointer)
    vowel_active_index: IntProperty("Active Index")
    consonants_active_index: IntProperty("Active Index")


class IMPLAB_OT_INSERT(Operator, ImportHelper):
    '''
    音素アクションをチェック
    台詞アクションを作る
    NLAトラックを作る
    NLAトラックにアクションを挿入
    '''
    bl_idname = "importlab.insert"
    bl_label = "挿入"
    bl_description = "指定したフレームに発音モーションを挿入する"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    filename_ext = ".lab"
    filter_glob: StringProperty(
        default="*.lab", options={'HIDDEN'}, maxlen=255)
    target: StringProperty(default="", options={'HIDDEN'})
    overwrite: BoolProperty(
        name="上書き", description="選択したファイルと同じ名前のアクションとストリップを削除してから生成、挿入します", default=True)
    use_scale: BoolProperty(
        name="Use Scale", description="固定フレームレートのアクションを生成し、再生スケールで調整する")

    def execute(self, context):
        print("IMPLAB : Insert Start")
        props = context.active_object.data.implab_props
        vowel_list = props.vowel_list
        consonants_list = props.consonants_list
        fps = context.scene.render.fps
        frametime = 1.0 / fps

        sentence = lab.lab_words(self.filepath).split()

        covering, phoneme_dict = self.phoneme_check(context)
        if self.overwrite:
            self.overwrite_preprocess(context)
        if not covering:
            return {"FINISHED"}
        match self.target:
            case 'ARMATURE':
                actions = self.generate_rig_action(
                    context, covering, sentence, phoneme_dict)
            case 'MESH':
                actions = self.generate_shapekey_action(
                    context, covering, sentence, phoneme_dict)
        track = self.create_track(context)
        self.insert_action_in_track(context, sentence, actions, track)

        return {"FINISHED"}

    def phoneme_check(self, context: Context) -> tuple[str, dict]:
        props = context.active_object.data.implab_props
        vlist = props.vowel_list
        clist = props.consonants_list
        obj = context.active_object

        # 音素スロットが一意か確認
        slots = [p for p in vlist] + [p for p in clist]
        unique = [v for i, v in enumerate(slots) if v.viseme in [
            l.viseme for l in slots[i+1:]]]
        if unique:
            for u in unique:
                self.report({'ERROR'}, f"一意ではない音素: {u.viseme}")
            return None, None

        # 音素辞書作成
        phoneme_dict = {v.viseme: v.pose for v in slots}

        if phoneme_dict['a'] != None and phoneme_dict['N'] != None:
            ret = 'OPEN_SHUT'
        else:
            self.report({'ERROR'}, "最低限のアクションが指定されていません: 'a' , 'N'")
            return None, None
        if len(vlist) >= 3 and None not in [v.pose for v in vlist]:
            ret = 'VOWEL'
        if len(clist) > 0 and None not in [v.pose for v in clist]:
            ret += '_CONSONANTS'
        return ret, phoneme_dict

    def overwrite_preprocess(self, context: Context):
        if self.target == 'ARMATURE':
            data = context.active_object.animation_data
        elif self.target == 'MESH':
           data = context.active_object.data.shape_keys.animation_data
        if data:
            name = bpy.path.display_name_from_filepath(self.filepath)
            if (track := data.nla_tracks.find("LAB Speech")) == -1:
                return
            strips = data.nla_tracks[track].strips
            for strip in [s for s in strips if re.fullmatch(f"{name}(\.[0-9]+)?$", s.name)]:
                action = strip.action
                strips.remove(strip)
                bpy.data.actions.remove(action)

    def generate_rig_action(self, context: Context, covering: str, sentence: list[lab.lab_words], phoneme_dict: dict[str, Action]):
        props = context.active_object.data.implab_props
        obj = context.active_object
        fps = 100 if self.use_scale else context.scene.render.fps

        a = phoneme_dict['a']
        N = phoneme_dict['N']

        vlist = {v.viseme: v.pose if v.pose else a for v in props.vowel_list}
        clist = {c.viseme: c.pose if c.pose else N for c in props.consonants_list}
        src_list: dict[str, Action] = vlist | clist
        actionname = bpy.path.display_name_from_filepath(self.filepath)

        action_list = []
        for s in sentence:
            act: Action = bpy.data.actions.new(actionname)
            # ファイル先頭の'pau'を'N'にする
            if act.name == actionname and s.phoneme_list[0].phoneme == 'pau':
                s.phoneme_list[0].phoneme = 'N'
            for p in s.phoneme_list:
                if p.phoneme not in src_list.keys():
                    continue
                phoneme = src_list[p.phoneme]
                timing = (((p.timingB + p.timingE)/2)*fps,)

                if p.length() > 0.1:  # 発音が長い場合、タイミングを2つ作る
                    timing = ((p.timingB + 0.05) * fps,
                              (p.timingE - 0.05) * fps)

                for src_fcurve in phoneme.fcurves:  # 音素のFカーブをアクションに打ち込む
                    index = src_fcurve.array_index
                    fcurve = act.fcurves.find(
                        src_fcurve.data_path, index=index)
                    if not fcurve:
                        fcurve = act.fcurves.new(
                            src_fcurve.data_path, index=index, action_group=src_fcurve.group.name)
                    for keyframe in src_fcurve.keyframe_points:
                        for t in timing:  # 発音が長い場合、キーフレームを2つ打つ
                            frame, value = keyframe.co
                            fcurve.keyframe_points.insert(
                                t, value, options={'FAST'})

            for curve in act.fcurves:
                curve.update()
            act.use_fake_user = True
            action_list.append(act)
        return action_list

    def generate_shapekey_action(self, context: Context, covering: str, sentence: list[lab.lab_words], phoneme_dict: dict[str, str]):
        props = context.active_object.data.implab_props
        obj = context.active_object
        fps = 100 if self.use_scale else context.scene.render.fps

        a = phoneme_dict['a']
        N = phoneme_dict['N']

        keys = obj.data.shape_keys.key_blocks
        vlist = {v.viseme: keys[v.pose]
                 if v.pose else a for v in props.vowel_list}
        clist = {c.viseme: keys[c.pose]
                 if c.pose else N for c in props.consonants_list}
        src_list: dict[str, ShapeKey] = vlist | clist
        actionname = bpy.path.display_name_from_filepath(self.filepath)

        action_list = []
        for s in sentence:
            act: Action = bpy.data.actions.new(actionname)
            # ファイル先頭の'pau'を'N'にする
            if act.name == actionname and s.phoneme_list[0].phoneme == 'pau':
                s.phoneme_list[0].phoneme = 'N'
            for p in s.phoneme_list:
                if p.phoneme not in src_list.keys():
                    continue
                phoneme = src_list[p.phoneme]

                # タイミング生成
                timing = [((p.timingB - 0.05), 0.0)]
                if p.length() > 0.1:  # 発音が長い場合、タイミングを2つ作る
                    timing.extend([(p.timingB + 0.05, 1.0),
                                  (p.timingE - 0.05, 1.0)])
                else:
                    timing.append(((p.timingB+p.timingE)/2, 1.0))
                timing.append((p.timingE+0.05, 0.0))

                # キーフレーム打ち込み
                shapekeyname = f"key_blocks[\"{phoneme.name}\"].value"
                if not (fcurve := act.fcurves.find(shapekeyname)):
                    fcurve = act.fcurves.new(shapekeyname)
                for t, v in timing:
                    fcurve.keyframe_points.insert(
                        t*fps, v, options={'FAST'})

            for curve in act.fcurves:
                curve.update()
            act.use_fake_user = True
            action_list.append(act)
        return action_list

    def create_track(self, context: Context):
        obj = context.active_object

        match obj.type:
            case 'ARMATURE':
                target = obj
            case 'MESH':
                target = obj.data.shape_keys

        if not target.animation_data:
            target.animation_data_create()
        nla_tracks = target.animation_data.nla_tracks

        if (id := nla_tracks.find("LAB Speech")) != -1:
            return nla_tracks[id]
        else:
            track = nla_tracks.new()
            track.name = "LAB Speech"
            return track

    def insert_action_in_track(self, context: Context, sentence: list[lab.lab_words], action_list: list[Action], track):
        obj = context.active_object
        current_frame = context.scene.frame_current

        for words, action in zip(sentence, action_list):
            p = words.phoneme_list[1] if words.phoneme_list[0].phoneme == 'pau' else words.phoneme_list[0]
            insert_frame = (p.timingB+0.05 if p.length() > 0.1 else (p.timingB+p.timingE)/2) * \
                context.scene.render.fps + current_frame

            strip = track.strips.new(action.name, int(insert_frame), action)
            strip.extrapolation = 'NOTHING'
            if self.use_scale:
                strip.scale = context.scene.render.fps / 100.0

        # for index in range(len(action_list[1:])):
        #     bpy.ops.nla.transition_add()


class IMPLAB_OT_SET_CURRENT_FRAME(Operator):
    bl_idname = "importlab.set_current_frame"
    bl_label = "現在のフレーム"
    bl_description = "挿入フレームを現在のフレームに合わせる"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        frame = context.active_object.data.implab_props.insert_frame
        context.active_object.data.implab_props.insert_frame = context.scene.frame_current
        print(
            f"IMPLAB : Set Insert Frame: {frame} to {context.active_object.data.implab_props.insert_frame}")
        return {"FINISHED"}


class IMPLAB_OT_SetPhonemeList(Operator):
    bl_idname = "importlab.set_phoneme_list"
    bl_label = "口形素リストを追加（日本語）"
    bl_description = "日本語の口形素リストを追加する"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.active_object.data.implab_props
        vl = lab.phoneme.vowel_literals
        cl = lab.phoneme.consonants_literals
        for p in range(len(vl)):
            if vl[p] not in [a.viseme for a in props.vowel_list]:
                #props.vowel_list[vl[p]] = ImplabActionPointer(vl[p])
                a = props.vowel_list.add()
                a.viseme = vl[p]
        for p in range(len(cl)):
            if cl[p] not in [a.viseme for a in props.consonants_list]:
                a = props.consonants_list.add()
                a.viseme = cl[p]
        return {"FINISHED"}


class IMPLAB_OT_NewVowel(Operator):
    bl_idname = "importlab.new_vowel"
    bl_label = "要素を追加"

    @classmethod
    def poll(cls, context):
        return hasattr(context.active_object.data.implab_props.vowel_list, 'add')

    def execute(self, context):
        props = context.active_object.data.implab_props
        v = props.vowel_list.add()
        return {"FINISHED"}


class IMPLAB_OT_DeleteVowel(Operator):
    bl_idname = "importlab.delete_vowel"
    bl_label = "要素を削除"

    @classmethod
    def poll(cls, context):
        return context.active_object.data.implab_props.vowel_list

    def execute(self, context):
        props = context.active_object.data.implab_props
        index = props.vowel_active_index
        props.vowel_list.remove(index)
        props.vowel_active_index = min(
            max(0, index-1), len(props.vowel_list)-1)
        return {"FINISHED"}


class IMPLAB_OT_MoveVowel(Operator):
    bl_idname = "importlab.move_vowel"
    bl_label = "要素を移動"

    direction: EnumProperty(items=(('UP', 'Up', ""), ('DOWN', 'Down', "")))

    @classmethod
    def poll(cls, context):
        return context.active_object.data.implab_props.vowel_list

    def execute(self, context):
        props = context.active_object.data.implab_props
        index = props.vowel_active_index

        if self.direction == 'UP':
            if props.vowel_active_index > 0:
                props.vowel_list.move(
                    props.vowel_active_index-1, props.vowel_active_index)
                context.active_object.data.implab_props.vowel_active_index -= 1
        elif self.direction == 'DOWN':
            if props.vowel_active_index < len(props.vowel_list)-1:
                props.vowel_list.move(
                    props.vowel_active_index+1, props.vowel_active_index)
                context.active_object.data.implab_props.vowel_active_index += 1
        return {"FINISHED"}


class IMPLAB_OT_NewConsonants(Operator):
    bl_idname = "importlab.new_consonants"
    bl_label = "要素を追加"

    @classmethod
    def poll(cls, context):
        return context.active_object.data.implab_props.consonants_list

    def execute(self, context):
        props = context.active_object.data.implab_props
        v = props.consonants_list.add()
        return {"FINISHED"}


class IMPLAB_OT_DeleteConsonants(Operator):
    bl_idname = "importlab.delete_consonants"
    bl_label = "要素を削除"

    @classmethod
    def poll(cls, context):
        return context.active_object.data.implab_props.consonants_list

    def execute(self, context):
        props = context.active_object.data.implab_props
        index = props.consonants_active_index
        props.consonants_list.remove(index)
        props.consonants_active_index = min(
            max(0, index-1), len(props.consonants_list)-1)
        return {"FINISHED"}


class IMPLAB_OT_MoveConsonants(Operator):
    bl_idname = "importlab.move_consonants"
    bl_label = "要素を移動"

    direction: EnumProperty(items=(('UP', 'Up', ""), ('DOWN', 'Down', "")))

    @classmethod
    def poll(cls, context):
        return context.active_object.data.implab_props.consonants_list

    def execute(self, context):
        props = context.active_object.data.implab_props
        index = props.consonants_active_index

        if self.direction == 'UP':
            if props.consonants_active_index > 0:
                props.consonants_list.move(
                    props.consonants_active_index-1, props.consonants_active_index)
                context.active_object.data.implab_props.consonants_active_index -= 1
        elif self.direction == 'DOWN':
            if props.consonants_active_index < len(props.consonants_list)-1:
                props.consonants_list.move(
                    props.consonants_active_index+1, props.consonants_active_index)
                context.active_object.data.implab_props.consonants_active_index += 1
        return {"FINISHED"}


class IMPLAB_PT_ImplabPanel(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_label = "Import Lab Pose"
    bl_options = {'DEFAULT_CLOSED'}
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not context.active_object:
            return False
        return obj.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        addon_prefs = bpy.context.preferences.addons[__package__].preferences
        props = context.active_object.data.implab_props

        layout.label(text="発音モーション挿入")
        # row = layout.row(align=True)
        # row.prop(props, "insert_frame")
        # size = row.operator(
        #     IMPLAB_OT_SET_CURRENT_FRAME.bl_idname, text="", icon="TIME")
        layout.operator(IMPLAB_OT_INSERT.bl_idname).target = 'ARMATURE'
        layout.operator(IMPLAB_OT_SetPhonemeList.bl_idname)


def uilist_draw(layout: 'bpy.types.UILayout', props, listtype_name, propname, active_propname, rows=5):
    row = layout.row(align=False)
    row.template_list(listtype_name, "",
                      props, propname, props, active_propname, rows=rows)
    col = row.column()
    col1 = col.column(align=True)
    col1.operator(IMPLAB_OT_NewVowel.bl_idname, text="", icon="ADD")
    col1.operator(IMPLAB_OT_DeleteVowel.bl_idname, text="", icon="REMOVE")
    col2 = col.column(align=True)
    col2.operator(IMPLAB_OT_MoveVowel.bl_idname,
                  text="", icon="TRIA_UP").direction = "UP"
    col2.operator(IMPLAB_OT_MoveVowel.bl_idname, text="",
                  icon="TRIA_DOWN").direction = "DOWN"


class IMPLAB_UL_PhonemeList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            if item:
                layout.prop(item, "viseme", text="",
                            emboss=False, icon_value=icon)
                layout.prop(item, "pose", text="")
            else:
                layout.label(text="", translate=False, icon_value=icon)
            #row = layout.split(align=True,factor=0.1)
            #row.prop(item, "viseme", text="", emboss=False)
            #row.prop(item, "pose", text="")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)


class IMPLAB_UL_PhonemeList2(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.split(align=True, factor=0.1)
            row.prop(item, "viseme", text="", emboss=False)
            row.prop(item, "pose", text="")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)


class IMPLAB_PT_vowel(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_label = "母音"
    bl_options = {'DEFAULT_CLOSED'}
    bl_context = "data"
    bl_parent_id = "IMPLAB_PT_ImplabPanel"

    def draw(self, context):
        layout = self.layout
        props = context.active_object.data.implab_props
        addon_prefs = bpy.context.preferences.addons[__package__].preferences

        uilist_draw(layout, props, "IMPLAB_UL_PhonemeList",
                    "vowel_list", "vowel_active_index", 6)


class IMPLAB_PT_consonants(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_label = "子音"
    bl_options = {'DEFAULT_CLOSED'}
    bl_context = "data"
    bl_parent_id = "IMPLAB_PT_ImplabPanel"

    def draw(self, context):
        layout = self.layout
        props = context.active_object.data.implab_props
        addon_prefs = bpy.context.preferences.addons[__package__].preferences

        uilist_draw(layout, props, "IMPLAB_UL_PhonemeList",
                    "consonants_list", "consonants_active_index")


class IMPLAB_PT_ImplabPanelMesh(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_label = "Import Lab Shapekey"
    bl_options = {'DEFAULT_CLOSED'}
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not context.active_object:
            return False
        return obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        addon_prefs = bpy.context.preferences.addons[__package__].preferences
        props = context.active_object.data.implab_props

        layout.label(text="発音モーション挿入")
        layout.operator(IMPLAB_OT_INSERT.bl_idname).target = 'MESH'
        layout.operator(IMPLAB_OT_SetPhonemeList.bl_idname)


class IMPLAB_PT_vowelMesh(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_label = "母音"
    bl_options = {'DEFAULT_CLOSED'}
    bl_context = "data"
    bl_parent_id = "IMPLAB_PT_ImplabPanelMesh"

    def draw(self, context):
        layout = self.layout
        props = context.active_object.data.implab_props

        uilist_draw(layout, props, "IMPLAB_UL_PhonemeList",
                    "vowel_list", "vowel_active_index", 6)


class IMPLAB_PT_consonantsMesh(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_label = "子音"
    bl_options = {'DEFAULT_CLOSED'}
    bl_context = "data"
    bl_parent_id = "IMPLAB_PT_ImplabPanelMesh"

    def draw(self, context):
        layout = self.layout
        props = context.active_object.data.implab_props

        uilist_draw(layout, props, "IMPLAB_UL_PhonemeList",
                    "consonants_list", "consonants_active_index")


# Blenderに登録するクラス
classes = [
    IMPLAB_MT_AddonPreferences,
    ImplabActionPointer,
    ImplabPropertyGroup,
    ImplabShapekeyPointer,
    ImplabMeshPropertyGroup,
    IMPLAB_OT_INSERT,
    IMPLAB_OT_SET_CURRENT_FRAME,
    IMPLAB_OT_SetPhonemeList,
    IMPLAB_OT_NewVowel,
    IMPLAB_OT_DeleteVowel,
    IMPLAB_OT_MoveVowel,
    IMPLAB_OT_NewConsonants,
    IMPLAB_OT_DeleteConsonants,
    IMPLAB_OT_MoveConsonants,
    IMPLAB_PT_ImplabPanel,
    IMPLAB_UL_PhonemeList,
    IMPLAB_UL_PhonemeList2,
    IMPLAB_PT_vowel,
    IMPLAB_PT_consonants,
    IMPLAB_PT_ImplabPanelMesh,
    IMPLAB_PT_vowelMesh,
    IMPLAB_PT_consonantsMesh
]

# アドオン有効化時の処理


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Armature.implab_props = bpy.props.PointerProperty(
        type=ImplabPropertyGroup)
    bpy.types.Mesh.implab_props = bpy.props.PointerProperty(
        type=ImplabMeshPropertyGroup)

    print("アドオン\"Inport Lab\"が有効化されました。")


# アドオン無効化時の処理
def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
    del bpy.types.Armature.implab_props
    del bpy.types.Mesh.implab_props
    print("アドオン\"Inport Lab\"が無効化されました。")


# メイン処理
if __name__ == "__main__":
    register()
