from eolearn.core import EOTask, EOPatch, LinearWorkflow, FeatureType, OverwritePermission, \
    LoadFromDisk, SaveToDisk, EOExecutor
import numpy as np
import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
from eolearn.io import S2L1CWCSInput, S2L1CWMSInput
from shapely.geometry import Polygon
import os
from sentinelhub import BBoxSplitter, BBox, CRS, CustomUrlParam
import datetime as dt
import time
from sklearn.utils import resample
import random
import pandas as pd
import collections


def sample_patches(path, no_patches, no_samples, class_feature, mask_feature, features, samples_per_class=None,
                   debug=False):
    '''
    :param path: Path to patch folder
    :param no_patches: total number of patches. Each has to be in its own folder named eopatch_{number}
    :param no_samples: Number of samples per patch
    :param class_feature: name of feature that contains class number and nan for no class
    :param mask_feature: feature that masks area from sampling (like edges), can be None then whole image is used
    :type mask_feature: None or binary 2D array
    :param features: features to include in returned dataset for each sample pixel
    :param samples_per_class: if None the minimal number is used. If set to a number its upsampled if too high
    :type samples_per_class: None or int
    :param debug: if set to True patch id and coordinates are included
    :return: Dataframe with columns [class feature, features, patch_id, x coord, y coord] id,x,y used for testing
    '''

    columns = [class_feature[1]] + [x[1] for x in features]
    if debug:
        columns = columns + ['patch_no', 'x', 'y']
    class_name = class_feature[1]
    sample_dict = []

    for patch_id in range(no_patches):
        eopatch = EOPatch.load('{}/eopatch_{}'.format(path, patch_id))
        _, height, width, _ = eopatch.data['BANDS'].shape
        mask = eopatch[mask_feature[0]][mask_feature[1]].squeeze()
        no_samples = min(height * width, no_samples)
        subsample_id = []
        for h in range(height):
            for w in range(width):
                if mask is None or mask[h][w] == 1:
                    subsample_id.append((h, w))
        subsample_id = random.sample(subsample_id, no_samples)

        for h, w in subsample_id:
            class_value = float(eopatch[class_feature[0]][class_feature[1]][h][w])
            if np.isnan(class_value):
                class_value = float(-1)

            array_for_dict = [(class_name, class_value)] + [(f[1], float(eopatch[f[0]][f[1]][h][w])) for f in features]
            if debug:
                array_for_dict += [('patch_no', patch_id), ('x', w), ('y', h)]
            sample_dict.append(dict(array_for_dict))

    df = pd.DataFrame(sample_dict, columns=columns)
    class_count = collections.Counter(df[class_feature[1]]).most_common()
    least_common = class_count[-1][1]

    replace = False
    if samples_per_class is not None:
        least_common = samples_per_class
        replace = True
        print('samples: ' + str(samples_per_class))
    df_downsampled = pd.DataFrame(columns=columns)
    names = [name[0] for name in class_count]
    dfs = [df[df[class_name] == x] for x in names]
    for d in dfs:
        nd = resample(d, replace=replace, n_samples=least_common)
        df_downsampled = df_downsampled.append(nd)

    return df_downsampled


# Example of usage
if __name__ == '__main__':
    # path = 'E:/Data/PerceptiveSentinel'
    path = '/home/beno/Documents/test/Slovenia'

    no_patches = 3
    no_samples = 10000
    class_feature = (FeatureType.MASK_TIMELESS, 'LPIS_2017')
    mask = (FeatureType.MASK_TIMELESS, 'EDGES_INV')
    features = [(FeatureType.DATA_TIMELESS, 'NDVI_mean_val'), (FeatureType.DATA_TIMELESS, 'SAVI_max_val'),
                (FeatureType.DATA_TIMELESS, 'NDVI_pos_surf')]
    samples_per_class = None
    debug = True

    samples = sample_patches(path, no_patches, no_samples, class_feature, mask, features, samples_per_class, debug)
    print(samples)