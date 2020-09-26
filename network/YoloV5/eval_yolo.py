import torch
from options import opt
import numpy as np
import torch.optim as optim
import torch.nn as nn
from torchvision import datasets, transforms
import gc
import ipdb
import misc_utils as utils

import yolo3.dataset
from yolo3.utils import *
from yolo3.image import correct_yolo_boxes
from yolo3.eval_map import eval_detection_voc
from torch_template.utils.torch_utils import write_loss
from yolo3.darknet import Darknet
import argparse

# global variables
# Training settings
# Train parameters
use_cuda = True
eps = 1e-5
keep_backup = 5
save_interval = 1  # epoches
test_interval = 10  # epoches
dot_interval = 70  # batches

# Test parameters
evaluate = False
conf_thresh = 0.005
nms_thresh = 0.45
iou_thresh = 0.5


def eval_yolo(yolo, test_loader, epoch, writer, logger, dataname='val'):
    def truths_length(truths):
        for i in range(50):
            if truths[i][1] == 0:
                return i
        return 50

    yolo.eval()
    cur_model = yolo
    num_classes = cur_model.num_classes
    total = 0.0
    proposals = 0.0
    correct = 0.0

    if cur_model.net_name() == 'region':  # region_layer
        shape = (0, 0)
    else:
        shape = (512, 512)

    pred_bboxes = []
    pred_labels = []
    pred_scores = []
    gt_bboxes = []
    gt_labels = []
    gt_difficults = []
    with torch.no_grad():
        for i, sample in enumerate(test_loader):
            utils.progress_bar(i, len(test_loader), 'Eva... ')
            image = sample['image'].to(opt.device)
            target = sample['yolo_boxes'].to(opt.device)

            output = yolo(image)
            all_boxes = get_all_boxes(output, shape, conf_thresh, num_classes, 
                                    device=opt.device, only_objectness=0, 
                                    validation=True)

            line_bboxes = []
            line_labels = []
            line_scores = []
            gt_line_bboxes = []
            gt_line_labels = []
            #ipdb.set_trace()
            for k in range(len(all_boxes)):
                boxes = all_boxes[k]
                width = 512
                height = 512
                correct_yolo_boxes(boxes, width, height, width, height)
                boxes = np.array(nms(boxes, nms_thresh))

                for box in boxes:
                    x1 = (box[0] - box[2] / 2.0) * width
                    y1 = (box[1] - box[3] / 2.0) * height
                    x2 = (box[0] + box[2] / 2.0) * width
                    y2 = (box[1] + box[3] / 2.0) * height

                    det_conf = box[4]
                    for j in range((len(box) - 5) // 2):
                        cls_conf = box[5 + 2 * j]
                        cls_id = int(box[6 + 2 * j])
                        prob = det_conf * cls_conf
                        line_bboxes.append([x1, y1, x2, y2])
                        line_labels.append(cls_id)
                        line_scores.append(prob)
                        # fps[cls_id].write('%s %f %f %f %f %f\n' % (fileId, prob, x1, y1, x2, y2))

                truths = target[k].view(-1, 5)
                num_gts = truths_length(truths)
                truths = truths[:num_gts]
                for label, b0, b1, b2, b3 in truths.detach().cpu().numpy():
                    x1 = (b0 - b2 / 2.0) * width
                    y1 = (b1 - b3 / 2.0) * height
                    x2 = (b0 + b2 / 2.0) * width
                    y2 = (b1 + b3 / 2.0) * height
                    gt_line_bboxes.append([x1, y1, x2, y2])
                    gt_line_labels.append(int(label))

            pred_bboxes.append(np.array(line_bboxes))
            pred_labels.append(np.array(line_labels))
            pred_scores.append(np.array(line_scores))
            gt_bboxes.append(np.array(gt_line_bboxes))
            gt_labels.append(np.array(gt_line_labels))
            gt_difficults.append(np.array([False] * num_gts))

    AP = eval_detection_voc(
            pred_bboxes,
            pred_labels,
            pred_scores,
            gt_bboxes,
            gt_labels,
            gt_difficults=None,
            iou_thresh=0.5,
            use_07_metric=False)

    APs = AP['ap']
    mAP = AP['map']

    logger.info(f'Eva({dataname}) epoch {epoch}, APs: {str(APs[:opt.num_classes])}, mAP: {mAP}')
    write_loss(writer, f'val/{dataname}', 'mAP', mAP, epoch)


    #
    # precision = 1.0 * correct / (proposals + eps)
    # recall = 1.0 * correct / (total + eps)
    # fscore = 2.0 * precision * recall / (precision + recall + eps)
    # # savelog("[%03d] correct: %d, precision: %f, recall: %f, fscore: %f" % (epoch, correct, precision, recall, fscore))
    # logger.info('Eva(RTTS) epoch %d, correct: %d, precision: %f, recall: %f, fscore: %f' % (epoch, correct, precision, recall, fscore))
    # write_loss(writer, 'val/%s' % 'RTTS', 'fscore', fscore, epoch)
    #
    # return correct, fscore
