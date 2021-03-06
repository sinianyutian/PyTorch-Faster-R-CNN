#--------------------------------------------
# Faster R-CNN
# Written by Hongyu Pan
#--------------------------------------------

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

from ..layers.rpn.rpn_layer import RPN
from ..layers.rpn.fpn_layer import FPN
from ..layers.loss.warp_smooth_l1_loss.warp_smooth_l1_loss import WarpSmoothL1Loss

from ..utils.config import cfg

from network import Network


class FasterRCNN(nn.Module):

    # def __init__(self, param_file_path):
    def __init__(self, pretrained=False):
        super(FasterRCNN, self).__init__()

        # parameters
        # self.param = _get_parameters(param_file_path)

        """
        network

        needs: net_name, feature_layers, num_classes

        basic_network is used to extract the features
        fpn/rpn network is used to calculate the proposal bounding-box and act on the features, which are extracted by the basic_network.
        roi_pooling_layer is in the rpn network.
        rcnn network is used to deal with the features, which are extracted by the roi pooling.

        """

        # get the basic_network and rcnn network
        # self.basic_network, self.rcnn = Network(
        # self.param.net_name, feature_layers=self.param.feature_layers, is_det=True)
        self.basic_network, self.rcnn = Network(
            cfg.NET_NAME, feature_layers=cfg.FEATURE_LAYERS, pretrained=pretrained, is_det=True, use_fpn=cfg.USE_FPN)

        # FPN/RPN network
        if cfg.USE_FPN:
            self.fpn = FPN(num_classes=cfg.NCLASSES, in_channels=self.basic_network.out_dim,
                           feat_strides=self.basic_network.feat_strides)
        else:
            self.rpn = RPN(num_classes=cfg.NCLASSES,
                           in_channel=self.basic_network.out_dim[0], feat_stride=self.basic_network.feat_strides[0])

        # classification and bbox regression
        self.cls_fc = nn.Linear(self.rcnn.out_dim, cfg.NCLASSES)
        self.bbox_fc = nn.Linear(self.rcnn.out_dim, cfg.NCLASSES * 4)

        self.cls_fc.weight.data.normal_(0, 0.1)
        self.cls_fc.bias.data.zero_()
        self.bbox_fc.weight.data.normal_(0, 0.1)
        self.bbox_fc.bias.data.zero_()

        # loss
        self.warp_smooth_l1_loss = WarpSmoothL1Loss(
            sigma=1.0, size_average=False)
        self.cross_entropy = None
        self.bbox_loss = None

        # for m in self.modules():
        # #print m
        # if isinstance(m, nn.Conv2d):
        # m.weight.data.normal_(0, 0.01)
        # if m.bias is not None:
        # m.bias.data.zero_()
        # elif isinstance(m, nn.BatchNorm2d):
        # m.weight.data.fill_(1)
        # m.bias.data.zero_()
        # elif isinstance(m, nn.Linear):
        # m.weight.data.normal_(0, 0.001)
        # if m.bias is not None:
        # m.bias.data.zero_()

    @property
    def loss(self):

        return self.cross_entropy + self.bbox_loss

    def forward(self, data, im_info, gt_boxes=None, gt_ishard=None, dontcare_areas=None):

        # extract the features
        features = self.basic_network(data)

        # roi_pooling_data is the feature calculated by the roi_pooling layer
        # rpn_data is the output of proposal_target_layer in the training phase, or the output of proposal_layer in the testing phase.
        if cfg.USE_FPN:
            roi_pooling_data, rpn_data = self.fpn(
                features, im_info, gt_boxes, gt_ishard, dontcare_areas)
        else:
            roi_pooling_data, rpn_data = self.rpn(
                features[0], im_info, gt_boxes, gt_ishard, dontcare_areas)

        output = self.rcnn(roi_pooling_data)

        cls_pred = self.cls_fc(output)
        bbox_pred = self.bbox_fc(output)

        if self.training:
            self.cross_entropy, self.bbox_loss = self.build_loss(
                cls_pred, bbox_pred, rpn_data[1], rpn_data[2], rpn_data[3], rpn_data[4])

        return cls_pred, bbox_pred, rpn_data[0]

    # calculate the classification loss and bounding-box delta regression loss
    def build_loss(self, cls_score, bbox_pred, labels, bbox_targets, bbox_inside_weights, bbox_outside_weights):

        if cls_score.is_cuda:
            labels = torch.autograd.Variable(torch.from_numpy(
                labels).type(new_type=torch.LongTensor)).cuda()
            if isinstance(bbox_pred.data, torch.cuda.FloatTensor):
                bbox_targets = torch.autograd.Variable(
                    torch.FloatTensor(bbox_targets)).cuda()
                bbox_inside_weights = torch.autograd.Variable(
                    torch.FloatTensor(bbox_inside_weights)).cuda()
                bbox_outside_weights = torch.autograd.Variable(
                    torch.FloatTensor(bbox_outside_weights)).cuda()
            elif isinstance(bbox_pred.data, torch.cuda.DoubleTensor):
                bbox_targets = torch.autograd.Variable(
                    torch.DoubleTensor(bbox_targets)).cuda()
                bbox_inside_weights = torch.autograd.Variable(
                    torch.DoubleTensor(bbox_inside_weights)).cuda()
                bbox_outside_weights = torch.autograd.Variable(
                    torch.DoubleTensor(bbox_outside_weights)).cuda()
        else:
            labels = torch.autograd.Variable(torch.from_numpy(
                labels).type(new_type=torch.LongTensor))
            if isinstance(bbox_pred.data, torch.FloatTensor):
                bbox_targets = torch.autograd.Variable(
                    torch.FloatTensor(bbox_targets))
                bbox_inside_weights = torch.autograd.Variable(
                    torch.FloatTensor(bbox_inside_weights))
                bbox_outside_weights = torch.autograd.Variable(
                    torch.FloatTensor(bbox_outside_weights))
            elif isinstance(bbox_pred.data, torch.DoubleTensor):
                bbox_targets = torch.autograd.Variable(
                    torch.DoubleTensor(bbox_targets))
                bbox_inside_weights = torch.autograd.Variable(
                    torch.DoubleTensor(bbox_inside_weights))
                bbox_outside_weights = torch.autograd.Variable(
                    torch.DoubleTensor(bbox_outside_weights))

        # print 'cls_score', cls_score
        # print 'labels', labels
        # print 'bbox_pred', bbox_pred
        # print 'bbox_targets', bbox_targets
        cross_entropy = F.cross_entropy(cls_score, labels, ignore_index=-1)

        bbox_loss = self.warp_smooth_l1_loss(
            bbox_pred, bbox_targets, bbox_inside_weights, bbox_outside_weights)

        return cross_entropy, bbox_loss
