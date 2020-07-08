# nuScenes dev-kit.
# Code written by Asha Asvathaman & Holger Caesar, 2020.

import json
import os.path as osp
import sys
import time
from collections import defaultdict
from typing import Any, List, Dict, Optional

import PIL
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
import numpy as np

from nuimages.utils.utils import annotation_name, mask_decode
from nuscenes.utils.color_map import get_colormap

PYTHON_VERSION = sys.version_info[0]

if not PYTHON_VERSION == 3:
    raise ValueError("nuScenes dev-kit only supports Python version 3.")


class NuImages:
    """
    Database class for nuImages to help query and retrieve information from the database.
    """

    def __init__(self,
                 version: str = 'v1.0-train',
                 dataroot: str = '/data/sets/nuimages',
                 lazy: bool = True,
                 verbose: bool = False):
        """
        Loads database and creates reverse indexes and shortcuts.
        :param version: Version to load (e.g. "v1.0-train", "v1.0-val").
        :param dataroot: Path to the tables and data.
        :param lazy: Whether to use lazy loading for the database tables.
        :param verbose: Whether to print status messages during load.
        """
        self.version = version
        self.dataroot = dataroot
        self.lazy = lazy
        self.verbose = verbose

        self.table_names = ['attribute', 'calibrated_sensor', 'category', 'ego_pose', 'log', 'object_ann', 'sample',
                            'sample_data', 'sensor', 'surface_ann']

        assert osp.exists(self.table_root), 'Database version not found: {}'.format(self.table_root)

        start_time = time.time()
        if verbose:
            print("======\nLoading nuImages tables for version {}...".format(self.version))

        # Init reverse indexing.
        self._token2ind: Dict[str, Optional[dict]] = dict()
        for table in self.table_names:
            self._token2ind[table] = None

        # Load tables directly if requested.
        if not self.lazy:
            # Explicitly init tables to help the IDE determine valid class members.
            self.attribute = self.__load_table__('attribute')
            self.calibrated_sensor = self.__load_table__('calibrated_sensor')
            self.category = self.__load_table__('category')
            self.ego_pose = self.__load_table__('ego_pose')
            self.log = self.__load_table__('log')
            self.object_ann = self.__load_table__('object_ann')
            self.sample = self.__load_table__('sample')
            self.sample_data = self.__load_table__('sample_data')
            self.sensor = self.__load_table__('sensor')
            self.surface_ann = self.__load_table__('surface_ann')

        self.color_map = get_colormap()
        self.sample_to_key_frame_map = None

        if verbose:
            print("Done loading in {:.1f} seconds (lazy={}).\n======".format(time.time() - start_time, self.lazy))

    def __getattr__(self, attr_name: str) -> Any:
        """
        Implement lazy loading for the database tables. Otherwise throw the default error.
        :param attr_name: The name of the variable to look for.
        :return: The dictionary that represents that table.
        """
        if attr_name in self.table_names:
            self.load_table(attr_name)
            return self.__getattribute__(attr_name)
        else:
            raise AttributeError("Error: %r object has no attribute %r" % (self.__class__.__name__, attr_name))

    def get(self, table_name: str, token: str) -> dict:
        """
        Returns a record from table in constant runtime.
        :param table_name: Table name.
        :param token: Token of the record.
        :return: Table record. See README.md for record details for each table.
        """
        assert table_name in self.table_names, "Table {} not found".format(table_name)

        return getattr(self, table_name)[self.getind(table_name, token)]

    def getind(self, table_name: str, token: str) -> int:
        """
        This returns the index of the record in a table in constant runtime.
        :param table_name: Table name.
        :param token: Token of the record.
        :return: The index of the record in table, table is an array.
        """
        # Lazy loading: Compute reverse indices.
        if self._token2ind[table_name] is None:
            self._token2ind[table_name] = dict()
            for ind, member in enumerate(getattr(self, table_name)):
                self._token2ind[table_name][member['token']] = ind

        return self._token2ind[table_name][token]

    @property
    def table_root(self) -> str:
        """
        Returns the folder where the tables are stored for the relevant version.
        """
        return osp.join(self.dataroot, self.version)

    def load_table(self, table_name) -> None:
        """
        Load a table, if it isn't already loaded.
        """

        if table_name in self.__dict__.keys():
            return
        else:
            table = self.__load_table__(table_name)
            self.__setattr__(table_name, table)

    def __load_table__(self, table_name) -> List[dict]:
        """
        Load a table and return it.
        :param table_name: The name of the table to load.
        :returns: The table dictionary.
        """

        start_time = time.time()
        table_path = osp.join(self.table_root, '{}.json'.format(table_name))
        assert osp.exists(table_path), 'Error: Table %s does not exist!' % table_name
        with open(table_path) as f:
            table = json.load(f)
        end_time = time.time()

        # Print a message to stdout.
        if self.verbose:
            print("Loaded {} {}(s) in {:.3f}s,".format(len(table), table_name, end_time - start_time))

        return table

    def list_attributes(self) -> None:
        """
        List all attributes and the number of annotations with each attribute.
        """
        # Load data if in lazy load to avoid confusing outputs.
        if self.lazy:
            self.load_table('attribute')
            self.load_table('object_ann')

        # Count attributes.
        attribute_freqs = defaultdict(lambda: 0)
        for object_ann in self.object_ann:
            for attribute_token in object_ann['attribute_tokens']:
                attribute_freqs[attribute_token] += 1

        # Print to stdout.
        format_str = '{:11} {:24.24} {:48.48}'
        print()
        print(format_str.format('Annotations', 'Name', 'Description'))
        for attribute in self.attribute:
            print(format_str.format(
                attribute_freqs[attribute['token']], attribute['name'], attribute['description']))

    def list_cameras(self) -> None:
        """
        List all cameras and the number of samples for each.
        """
        # Load data if in lazy load to avoid confusing outputs.
        if self.lazy:
            self.load_table('sample')
            self.load_table('sample_data')
            self.load_table('calibrated_sensor')
            self.load_table('sensor')

        # Count cameras.
        cs_freqs = defaultdict(lambda: 0)
        channel_freqs = defaultdict(lambda: 0)
        for calibrated_sensor in self.calibrated_sensor:
            sensor = self.get('sensor', calibrated_sensor['sensor_token'])
            cs_freqs[sensor['channel']] += 1
        for sample_data in self.sample_data:
            if sample_data['is_key_frame']:  # Only use keyframes (samples).
                calibrated_sensor = self.get('calibrated_sensor', sample_data['calibrated_sensor_token'])
                sensor = self.get('sensor', calibrated_sensor['sensor_token'])
                channel_freqs[sensor['channel']] += 1

        # Print to stdout.
        format_str = '{:7} {:6} {:24}'
        print()
        print(format_str.format('Cameras', 'Samples', 'Channel'))
        for channel in cs_freqs.keys():
            cs_freq = cs_freqs[channel]
            channel_freq = channel_freqs[channel]
            print(format_str.format(
                cs_freq, channel_freq, channel))

    def list_categories(self, sample_tokens: List[str] = None) -> None:
        """
        List all categories and the number of object_anns and surface_anns for them.
        :param sample_tokens: A list of sample tokens for which category stats will be shown.
        """
        # Load data if in lazy load to avoid confusing outputs.
        if self.lazy:
            self.load_table('sample')
            self.load_table('object_ann')
            self.load_table('surface_ann')
            self.load_table('category')

        # Count object_anns and surface_anns.
        object_freqs = defaultdict(lambda: 0)
        surface_freqs = defaultdict(lambda: 0)
        if sample_tokens is not None:
            sample_tokens = set(sample_tokens)
        for object_ann in self.object_ann:
            sample_token = self.get('sample_data', object_ann['sample_data_token'])['sample_token']
            if sample_tokens is None or sample_token in sample_tokens:
                object_freqs[object_ann['category_token']] += 1
        for surface_ann in self.surface_ann:
            sample_token = self.get('sample_data', surface_ann['sample_data_token'])['sample_token']
            if sample_tokens is None or sample_token in sample_tokens:
                surface_freqs[surface_ann['category_token']] += 1

        # Print to stdout.
        format_str = '{:11} {:12} {:24.24} {:48.48}'
        print()
        print(format_str.format('Object_anns', 'Surface_anns', 'Name', 'Description'))
        for category in self.category:
            category_token = category['token']
            object_freq = object_freqs[category_token]
            surface_freq = surface_freqs[category_token]

            # Skip empty categories.
            if object_freq == 0 and surface_freq == 0:
                continue

            name = category['name']
            description = category['description']
            print(format_str.format(
                object_freq, surface_freq, name, description))

    def list_logs(self) -> None:
        """
        List all logs and the number of samples per log.
        """
        # Load data if in lazy load to avoid confusing outputs.
        if self.lazy:
            self.load_table('sample')
            self.load_table('log')

        # Count samples.
        sample_freqs = defaultdict(lambda: 0)
        for sample in self.sample:
            sample_freqs[sample['log_token']] += 1

        # Print to stdout.
        format_str = '{:6} {:29} {:24}'
        print()
        print(format_str.format('Samples', 'Log', 'Location'))
        for log in self.log:
            sample_freq = sample_freqs[log['token']]
            logfile = log['logfile']
            location = log['location']
            print(format_str.format(
                sample_freq, logfile, location))

    def list_sample_content(self, sample_token: str) -> None:
        """
        List the sample_datas for a given sample.
        :param sample_token: Sample token.
        """
        # Load data if in lazy load to avoid confusing outputs.
        if self.lazy:
            self.load_table('sample_data')
            self.load_table('sample')

        sample_datas = [sd for sd in self.sample_data if sd['sample_token'] == sample_token]
        sample = self.get('sample', sample_token)

        # Print content for each modality.
        for modality in ['camera', 'lidar']:
            if modality == 'camera':
                fileformat = 'jpg'
            else:
                fileformat = 'bin'
            sample_datas_sel = [sd for sd in sample_datas if sd['fileformat'] == fileformat]
            sample_datas_sel.sort(key=lambda sd: sd['timestamp'])
            timestamps = np.array([sd['timestamp'] for sd in sample_datas_sel])
            rel_times = (timestamps - sample['timestamp']) / 1e6

            print('\nListing sample_datas for %s...' % modality)
            print('Rel. time\tSample_data token')
            for rel_time, sample_data in zip(rel_times, sample_datas_sel):
                print('{:>9.1f}\t{}'.format(rel_time, sample_data['token']))

    def sample_to_key_frame(self, sample_token: str, modality: str = 'camera') -> str:
        """
        Map from a sample to the sample_data of the keyframe.
        :param sample_token: Sample token.
        :param modality: The type of sample_data to select, camera or lidar.
        :return: The sample_data token of the keyframe.
        """
        # Precompute and store the mapping.
        if self.sample_to_key_frame_map is None:
            mapping = {'image': dict(), 'lidar': dict()}
            for sample_data in self.sample_data:
                if sample_data['is_key_frame']:
                    if sample_data['fileformat'] == 'jpg':
                        sd_modality = 'camera'
                    else:
                        sd_modality = 'lidar'
                    sd_sample_token = sample_data['sample_token']
                    mapping[sd_modality][sd_sample_token] = sample_data['token']

            self.sample_to_key_frame_map = mapping

        # Use the mapping
        sample_data_token = self.sample_to_key_frame_map[modality][sample_token]

        return sample_data_token

    def render_image(self,
                     sample_data_token: str,
                     with_annotations: bool = True,
                     with_attributes: bool = False,
                     object_tokens: List[str] = None,
                     surface_tokens: List[str] = None,
                     render_scale: float = 2.0,
                     ax: Axes = None) -> PIL.Image:
        """
        Renders an image (sample_data), optionally with annotations overlaid.
        :param sample_data_token: The token of the sample_data to be rendered.
        :param with_annotations: Whether to draw all annotations.
        :param with_attributes: Whether to include attributes in the label tags.
        :param object_tokens: List of object annotation tokens. If given, only these annotations are drawn.
        :param surface_tokens: List of surface annotation tokens. If given, only these annotations are drawn.
        :param render_scale: The scale at which the image will be rendered.
        :param ax: The matplotlib axes where the layer will get rendered or None to create new axes.
        :return: Image object.
        """
        # Validate inputs.
        sample_data = self.get('sample_data', sample_data_token)
        assert sample_data['fileformat'] == 'jpg', 'Error: Cannot use render_image() on lidar pointclouds!'
        if not sample_data['is_key_frame']:
            assert not with_annotations, 'Error: Cannot render annotations for non keyframes!'
            assert not with_attributes, 'Error: Cannot render attributes for non keyframes!'

        # Get image data.
        im_path = osp.join(self.dataroot, sample_data['filename'])
        im = PIL.Image.open(im_path)
        if not with_annotations:
            return im

        # Initialize drawing.
        font = PIL.ImageFont.load_default()
        draw = PIL.ImageDraw.Draw(im, 'RGBA')

        # Load stuff / background regions.
        surface_anns = [o for o in self.surface_ann if o['sample_data_token'] == sample_data_token]
        if surface_tokens is not None:
            surface_anns = [o for o in surface_anns if o['token'] in surface_tokens]

        # Draw stuff / background regions.
        for ann in surface_anns:
            # Get color and mask
            category_token = ann['category_token']
            category_name = self.get('category', category_token)['name']
            color = self.color_map[category_name]
            if ann['mask'] is None:
                continue
            mask = mask_decode(ann['mask'])

            draw.bitmap((0, 0), PIL.Image.fromarray(mask * 128), fill=tuple(color + (128,)))

        # Load object instances.
        object_anns = [o for o in self.object_ann if o['sample_data_token'] == sample_data_token]
        if object_tokens is not None:
            object_anns = [o for o in object_anns if o['token'] in object_tokens]

        # Draw object instances.
        for ann in object_anns:
            # Get color, box, mask and name.
            category_token = ann['category_token']
            category_name = self.get('category', category_token)['name']
            color = self.color_map[category_name]
            bbox = ann['bbox']
            attr_tokens = ann['attribute_tokens']
            attributes = [self.get('attribute', at) for at in attr_tokens]
            name = annotation_name(attributes, category_name, with_attributes=with_attributes)
            if ann['mask'] is None:
                continue
            mask = mask_decode(ann['mask'])

            # Draw rectangle, text and mask.
            draw.rectangle(bbox, outline=color)
            draw.text((bbox[0], bbox[1]), name, font=font)
            draw.bitmap((0, 0), PIL.Image.fromarray(mask * 128), fill=tuple(color + (128,)))

        # Plot the image.
        if ax is None:
            _, ax = plt.subplots(1, 1, figsize=(9 * render_scale, 16 * render_scale))
        ax.imshow(im)
        (width, height) = im.size
        ax.set_xlim(0, width)
        ax.set_ylim(height, 0)
        ax.set_title(sample_data_token)
        ax.axis('off')

        return im
