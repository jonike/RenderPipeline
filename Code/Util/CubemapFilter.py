
from __future__ import division

from panda3d.core import Texture

from .DebugObject import DebugObject
from .Image import Image

class CubemapFilter(DebugObject):
    
    """ Util class for filtering cubemaps, provides funcionality to generate
    a specular and diffuse IBL cubemap. """

    # Fixed size for the diffuse cubemap, since it does not contain much detail
    DIFFUSE_CUBEMAP_SIZE = 10
    PREFILTER_CUBEMAP_SIZE = 32

    def __init__(self, parent_stage, name="Cubemap", size=256):
        """ Inits the filter from a given stage """
        self._stage = parent_stage
        self._name = name
        self._size = size
        self._make_maps()

    def get_specular_cubemap(self):
        """ Returns the generated specular cubemap. The specular cubemap is
        mipmapped and provides the specular IBL components of the input cubemap. """
        return self._specular_map.texture

    specular_cubemap = property(get_specular_cubemap)

    def get_diffuse_cubemap(self):
        """ Returns the generated diffuse cubemap. The diffuse cubemap has no
        mipmaps and contains the filtered diffuse component of the input cubemap. """
        return self._diffuse_map.texture

    diffuse_cubemap = property(get_diffuse_cubemap)

    def get_target_cubemap(self):
        """ Returns the target where the caller should write the initial cubemap
        data to """
        return self._specular_map.texture

    target_cubemap = property(get_target_cubemap)

    def get_size(self):
        """ Returns the size of the created cubemap, previously passed to the
        constructor of the filter """
        return self._size

    size = property(get_size)

    def create(self):
        """ Creates the filter. The input cubemap should be mipmapped, and will
        get reused for the specular cubemap. """
        self._make_specular_targets()
        self._make_diffuse_target()

    def _make_maps(self):
        """ Internal method to create the cubemap storage """

        # Create the cubemaps for the diffuse and specular components
        self._prefilter_map = Image.create_cube(
            self._name + "IBLPrefDiff", CubemapFilter.PREFILTER_CUBEMAP_SIZE,
            Texture.T_float, Texture.F_r11_g11_b10)
        self._diffuse_map = Image.create_cube(
            self._name + "IBLDiff", CubemapFilter.DIFFUSE_CUBEMAP_SIZE,
            Texture.T_float, Texture.F_r11_g11_b10)
        self._spec_pref_map = Image.create_cube(
            self._name + "IBLPrefSpec", self._size, Texture.T_float, Texture.F_r11_g11_b10)
        self._specular_map = Image.create_cube(
            self._name + "IBLSpec", self._size, Texture.T_float, Texture.F_r11_g11_b10)

        # Set the correct filtering modes
        for tex in [self._diffuse_map, self._specular_map, self._prefilter_map]:
            tex.texture.set_minfilter(Texture.FT_linear)
            tex.texture.set_magfilter(Texture.FT_linear)

        # Use mipmaps for the specular cubemap
        self._spec_pref_map.texture.set_minfilter(Texture.FT_linear_mipmap_linear)
        self._specular_map.texture.set_minfilter(Texture.FT_linear_mipmap_linear)

    def _make_specular_targets(self):
        """ Internal method to create the specular mip chain """
        self._targets_spec = []
        self._targets_spec_filter = []
        mip, mipsize = 0, self._size
        while mipsize >= 2:

            # Assuming an initial size of a power of 2, its safe to do this
            mipsize = mipsize // 2

            # Create the target which downsamples the mipmap
            target = self._stage._create_target(
                self._name + "SpecIBL-" + str(mipsize))
            target.set_size(mipsize * 6, mipsize)
            target.prepare_offscreen_buffer()

            if mip == 0:
                target.set_shader_input("SourceTex", self._specular_map.texture)
            else:
                target.set_shader_input("SourceTex", self._spec_pref_map.texture)
            target.set_shader_input(
                "DestMipmap", self._spec_pref_map.texture, False, True, -1,
                mip + 1, 0)
            target.set_shader_input("currentMip", mip)

            mip += 1

            # Create the target which filters the mipmap and removes the noise
            target_filter = self._stage._create_target(
                self._name + "SpecIBLFilter-" + str(mipsize))
            target_filter.set_size(mipsize * 6, mipsize)
            target_filter.prepare_offscreen_buffer()
            target_filter.set_shader_input("currentMip", mip)
            target_filter.set_shader_input("SourceTex", self._spec_pref_map.texture)
            target_filter.set_shader_input(
                "DestMipmap", self._specular_map.texture, False, True, -1, mip, 0)
            
            self._targets_spec.append(target)
            self._targets_spec_filter.append(target_filter)

    def _make_diffuse_target(self):
        """ Internal method to create the diffuse cubemap """

        # Create the target which integrates the lambert brdf
        self._diffuse_target = self._stage._create_target(self._name + "DiffuseIBL")
        self._diffuse_target.set_size(CubemapFilter.PREFILTER_CUBEMAP_SIZE * 6,
            CubemapFilter.PREFILTER_CUBEMAP_SIZE)
        self._diffuse_target.add_color_texture()
        self._diffuse_target.prepare_offscreen_buffer()

        self._diffuse_target.set_shader_input("SourceCubemap", self._specular_map.texture)
        self._diffuse_target.set_shader_input("DestCubemap", self._prefilter_map.texture)
        self._diffuse_target.set_shader_input("cubeSize", CubemapFilter.PREFILTER_CUBEMAP_SIZE)

        # Create the target which removes the noise from the previous target,
        # which is introduced with importance sampling
        self._diff_filter_target = self._stage._create_target(self._name + "DiffPrefIBL")
        self._diff_filter_target.set_size(CubemapFilter.DIFFUSE_CUBEMAP_SIZE * 6,
            CubemapFilter.DIFFUSE_CUBEMAP_SIZE)
        self._diff_filter_target.add_color_texture()
        self._diff_filter_target.prepare_offscreen_buffer()

        self._diff_filter_target.set_shader_input("SourceCubemap", self._prefilter_map.texture)
        self._diff_filter_target.set_shader_input("DestCubemap", self._diffuse_map.texture)
        self._diff_filter_target.set_shader_input("cubeSize", CubemapFilter.DIFFUSE_CUBEMAP_SIZE)

    def set_shaders(self):
        """ Sets all required shaders on the filter. """
        self._diffuse_target.set_shader(
            self._stage._load_shader("Stages/IBLCubemapDiffuse.frag"))
        self._diff_filter_target.set_shader(
            self._stage._load_shader("Stages/IBLCubemapDiffFilter.frag"))

        mip_shader = self._stage._load_shader("Stages/IBLCubemapSpecular.frag")
        for target in self._targets_spec:
            target.set_shader(mip_shader)

        mip_filter_shader = self._stage._load_shader("Stages/IBLCubemapSpecularFilter.frag")
        for target in self._targets_spec_filter:
            target.set_shader(mip_filter_shader)
