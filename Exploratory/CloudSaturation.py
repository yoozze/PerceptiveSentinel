import datetime

import numpy as np

from sentinelhub.data_request import WmsRequest, WcsRequest
from sentinelhub.constants import MimeType
from sentinelhub.common import BBox, CRS
from sentinelhub import CustomUrlParam

from s2cloudless import S2PixelCloudDetector

#INSTANCE_ID = open("INSTANCE_ID").read()
INSTANCE_ID = "b1062c36-3d9a-4df5-ad3d-ab0d40ae3ca0"


class CloudSaturation:
    class MemoData:
        def __init__(self, total_mask_w, true_color, bands, dates, cloud_masks):
            self.total_mask_w = total_mask_w
            self.true_color = np.array(true_color)
            self.bands = np.array(bands)
            self.dates = np.array(dates)
            self.cloud_masks = np.array(cloud_masks)

    def __init__(self,
                 coordinates,
                 start_time='2014-12-01',
                 end_time=datetime.datetime.now().strftime('%Y-%m-%d'),
                 data_folder_name="data/",
                 cloud_scale=6,
                 res=(10, 10),
                 redownload=False,
                 instance_id=INSTANCE_ID,
                 cloud_detector_config=
                 dict(threshold=0.4, average_over=4, dilation_size=2)
                 ):
        self.coordinates = coordinates
        self.bbox = BBox(bbox=self.coordinates, crs=CRS.WGS84)

        self.data_folder_name = data_folder_name
        self.start_time = start_time
        self.end_time = end_time
        self.time_range = (start_time, end_time)
        self.redownload = redownload
        self.instance_id = instance_id
        self.cloud_detection_config = cloud_detector_config
        self.res_x, self.res_y = res
        self.cloud_res_x = cloud_scale * self.res_x
        self.cloud_res_y = cloud_scale * self.res_y
        self.cloud_scale = cloud_scale
        self.memo_data = None  # type: CloudSaturation.MemoData

    def create_requests(self):
        bands_script = 'return [B01,B02,B04,B05,B08,B8A,B09,B10,B11,B12]'

        wms_true_color_request = WcsRequest(layer='TRUE_COLOR',
                                            bbox=self.bbox,
                                            data_folder=self.data_folder_name,
                                            time=self.time_range,
                                            resx=str(self.res_x) + "m",
                                            resy=str(self.res_y) + "m",
                                            image_format=MimeType.PNG,
                                            instance_id=self.instance_id,
                                            custom_url_params={
                                                CustomUrlParam.SHOWLOGO: False,
                                            },
                                            )
        cloud_bbox = list(self.coordinates)
        # To get one more pixel when downloading clouds
        # Note: Numbers are not precise
        cloud_bbox[2] += 0.001
        cloud_bbox[3] += 0.001
        # Note: large widths are much much slower and more computationally expensive
        wms_bands_request = WcsRequest(layer='TRUE_COLOR',
                                       data_folder=self.data_folder_name,
                                       custom_url_params={
                                           CustomUrlParam.EVALSCRIPT: bands_script,
                                           CustomUrlParam.SHOWLOGO: False},
                                       bbox=BBox(bbox=cloud_bbox, crs=CRS.WGS84),
                                       time=self.time_range,
                                       resx=str(self.cloud_res_x) + "m",
                                       resy=str(self.cloud_res_y) + "m",
                                       image_format=MimeType.TIFF_d32f,
                                       instance_id=self.instance_id)

        return wms_true_color_request, wms_bands_request

    def load_data(self):
        true_color_request, bands_request = self.create_requests()

        t_c_data = true_color_request.get_data(save_data=True,
                                               redownload=self.redownload)
        print("Saved True color")
        bands_data = bands_request.get_data(save_data=True,
                                            redownload=self.redownload)
        print("Saved bands")
        return t_c_data, bands_data, true_color_request.get_dates()

    @staticmethod
    def upscale_image(img, scale):
        return np.kron(img, np.ones((scale, scale)))

    @staticmethod
    def get_image_mask(image):
        return (image == 255).all(axis=2)

    def get_cloud_saturation_mask(self):
        cloud_detector = S2PixelCloudDetector(**self.cloud_detection_config)
        true_color, bands, dates = self.load_data()
        print("Downloaded")
        cloud_masks_orig = cloud_detector.get_cloud_masks(np.array(bands))
        # upscale cloud masks
        cloud_masks = []
        print(cloud_masks_orig[0].shape)
        for i in range(len(cloud_masks_orig)):
            cloud_masks.append(self.upscale_image(cloud_masks_orig[i], self.cloud_scale))
        cloud_masks = np.array(cloud_masks)
        print("Detected")
        # Images might be slightly out of scale, crop them
        x, y, _ = true_color[0].shape
        print(cloud_masks.shape)
        cloud_masks = cloud_masks[:, -x:, :y]
        print(cloud_masks.shape)
        print(true_color[0].shape)
        off_image_detection_mask = sum(map(self.get_image_mask, true_color))
        # Just sum how many times we detect white pixels

        full_cloud_mask = sum(cloud_masks)
        # Get total mask by dividing number of cloud detections by number of all sensible pixels
        total_mask_w = (full_cloud_mask / (
                len(cloud_masks) - off_image_detection_mask)).astype(float)

        self.memo_data = CloudSaturation.MemoData(total_mask_w, true_color, bands, dates, cloud_masks)

        return total_mask_w, np.array(true_color), np.array(bands), np.array(
            dates), np.array(cloud_masks)

    def get_full_index_timeseries(self, index_id):
        if self.memo_data is None:
            self.get_cloud_saturation_mask()
        wms_index_request = WcsRequest(layer=index_id,
                                       data_folder=self.data_folder_name,
                                       custom_url_params={
                                           CustomUrlParam.SHOWLOGO: False},
                                       bbox=self.bbox,
                                       time=self.time_range,
                                       resx=str(self.res_x) + "m",
                                       resy=str(self.res_y) + "m",
                                       image_format=MimeType.TIFF_d32f,
                                       instance_id=self.instance_id)
        data = wms_index_request.get_data(save_data=True,
                                          redownload=self.redownload)

        return np.array(data)

    def filter_index_timeseries(self, index_timeseries, x_ind, y_ind):
        if self.memo_data is None:
            self.get_cloud_saturation_mask()
        # Filter images
        # Choose 0 band as reference for non photographed
        nonzero_image_indices = np.nonzero(
            self.memo_data.bands[:, x_ind, y_ind, 0])
        nonzero_cloud_indices = np.nonzero(
            self.memo_data.cloud_masks[:, x_ind, y_ind])
        both_nonzero = np.intersect1d(nonzero_image_indices,
                                      nonzero_cloud_indices)

        return index_timeseries[both_nonzero, x_ind, y_ind], self.memo_data.dates[both_nonzero]

    def get_cloud_filter(self, x_ind, y_ind):
        if self.memo_data is None:
            self.get_cloud_saturation_mask()
        return np.nonzero(self.memo_data.cloud_masks[:, x_ind, y_ind])