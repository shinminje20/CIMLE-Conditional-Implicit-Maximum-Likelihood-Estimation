"""Downloads LPIPS data for use.
This avoids having to use the pip package, which is nice when <glares> pip
packages can't be installed.
Almost all code from the LPIPS repo:
https://github.com/richzhang/PerceptualSimilarity
Some is modified from CamNet:
https://github.com/niopeng/CAM-Net
"""
from os import path
import gdown
from tqdm import tqdm

import math
from collections import namedtuple
import torch
import torch.nn as nn
from torchvision import models as tv

def get_lpips_weights():
    """Downloads the LPIPS VGG16 weights. Our only contribution to this file!"""
    file = f"{path.dirname(f'{__file__}')}/vgg_lpips_weights.pth"
    if not path.exists(file):
        url = "https://drive.google.com/u/0/uc?id=1IQCDHxO-cYnFMx1hATjgSGQdO-_pB9nb&export=download"
        file = f"{path.dirname(f'{__file__}')}/vgg_lpips_weights.pth"
        gdown.download(url, file, quiet=False)

def normalize_tensor(x, eps=1e-10):
    """Returns tensor [x] after normalization."""
    norm_factor = torch.sqrt(torch.sum(x ** 2, dim=1, keepdim=True) + eps)
    return x / (norm_factor + eps)

class vgg16(torch.nn.Module):
    def __init__(self, requires_grad=False, pretrained=True):
        super(vgg16, self).__init__()
        vgg_pretrained_features = tv.vgg16(pretrained=pretrained).features
        self.slice1 = torch.nn.Sequential()
        self.slice2 = torch.nn.Sequential()
        self.slice3 = torch.nn.Sequential()
        self.slice4 = torch.nn.Sequential()
        self.slice5 = torch.nn.Sequential()
        self.N_slices = 5
        for x in range(4):
            if isinstance(vgg_pretrained_features[x], nn.ReLU):
                self.slice1.add_module(str(x), nn.ReLU(inplace=False))
            else:
                self.slice1.add_module(str(x), vgg_pretrained_features[x])
        for x in range(4, 9):
            if isinstance(vgg_pretrained_features[x], nn.ReLU):
                self.slice2.add_module(str(x), nn.ReLU(inplace=False))
            else:
                self.slice2.add_module(str(x), vgg_pretrained_features[x])
        for x in range(9, 16):
            if isinstance(vgg_pretrained_features[x], nn.ReLU):
                self.slice3.add_module(str(x), nn.ReLU(inplace=False))
            else:
                self.slice3.add_module(str(x), vgg_pretrained_features[x])
        for x in range(16, 23):
            if isinstance(vgg_pretrained_features[x], nn.ReLU):
                self.slice4.add_module(str(x), nn.ReLU(inplace=False))
            else:
                self.slice4.add_module(str(x), vgg_pretrained_features[x])
        for x in range(23, 30):
            if isinstance(vgg_pretrained_features[x], nn.ReLU):
                self.slice5.add_module(str(x), nn.ReLU(inplace=False))
            else:
                self.slice5.add_module(str(x), vgg_pretrained_features[x])

    def forward(self, X):
        # print("====================== vgg16 ===============================")
        # print("slice1 X.shpae: ", X.shape)
        h = self.slice1(X)
        h_relu1_2 = h
        # print("slice2 X.shpae: ", X.shape)
        h = self.slice2(h)
        h_relu2_2 = h
        # print("slice3 X.shpae: ", X.shape)
        h = self.slice3(h)
        h_relu3_3 = h
        # print("slice4 X.shpae: ", X.shape)
        h = self.slice4(h)
        h_relu4_3 = h
        # print("slice5 X.shpae: ", X.shape)
        h = self.slice5(h)
        h_relu5_3 = h
        vgg_outputs = namedtuple("VggOutputs", ['relu1_2', 'relu2_2', 'relu3_3', 'relu4_3', 'relu5_3'])
        out = vgg_outputs(h_relu1_2, h_relu2_2, h_relu3_3, h_relu4_3, h_relu5_3)
        # print("====================== ===== ===============================")
        return out

class LPIPSFeats(nn.Module):
    """Neural net for getting LPIPS features. Heavily modifed from CamNet."""

    def __init__(self):
        super(LPIPSFeats, self).__init__()
        self.vgg = vgg16()

        self.shift = nn.Parameter(torch.Tensor([-.030,-.088,-.188])[None,:,None,None])
        self.scale = nn.Parameter(torch.Tensor([.458,.448,.450])[None,:,None,None])

        get_lpips_weights()
        W = torch.load(f"{path.dirname(f'{__file__}')}/vgg_lpips_weights.pth")
        self.lin0 = nn.Parameter(torch.sqrt(W["lin0.model.1.weight"]))
        self.lin1 = nn.Parameter(torch.sqrt(W["lin1.model.1.weight"]))
        self.lin2 = nn.Parameter(torch.sqrt(W["lin2.model.1.weight"]))
        self.lin3 = nn.Parameter(torch.sqrt(W["lin3.model.1.weight"]))
        self.lin4 = nn.Parameter(torch.sqrt(W["lin4.model.1.weight"]))

        self.eval()

    def forward(self, x, normalize=True):
        """Returns an n_samples x 124928 tensor where each the ith row is the
        LPIPS features of the ith example in [x].
        Args:
        x           -- input to get LPIPS features for with shape B x C x H x W
        normalize   -- whether to normalize the input in 0...1 to -1...1
        """
        
        x = 2 * x - 1 if normalize else x
        x = (x - self.shift) / self.scale
        vgg_feats = [normalize_tensor(v) for v in self.vgg(x)]

        feats = [
            torch.multiply(self.lin0, vgg_feats[0]),
            torch.multiply(self.lin1, vgg_feats[1]),
            torch.multiply(self.lin2, vgg_feats[2]),
            torch.multiply(self.lin3, vgg_feats[3]),
            torch.multiply(self.lin4, vgg_feats[4])
        ]

        return [l.flatten(start_dim=1) for l in feats]

class LPIPSAndImageFeats(nn.Module):
    """Neural net for getting LPIPS features. Heavily modifed from CamNet.
    
    Inputs must be in [0, 1].
    """
    def __init__(self, alpha=.1):
        super(LPIPSAndImageFeats, self).__init__()
        self.vgg = vgg16()
        self.alpha = torch.tensor(alpha)

        self.shift = nn.Parameter(torch.Tensor([-.030,-.088,-.188])[None,:,None,None])
        self.scale = nn.Parameter(torch.Tensor([.458,.448,.450])[None,:,None,None])

        get_lpips_weights()
        W = torch.load(f"{path.dirname(f'{__file__}')}/vgg_lpips_weights.pth")
        self.lin0 = nn.Parameter(torch.sqrt(W["lin0.model.1.weight"]))
        self.lin1 = nn.Parameter(torch.sqrt(W["lin1.model.1.weight"]))
        self.lin2 = nn.Parameter(torch.sqrt(W["lin2.model.1.weight"]))
        self.lin3 = nn.Parameter(torch.sqrt(W["lin3.model.1.weight"]))
        self.lin4 = nn.Parameter(torch.sqrt(W["lin4.model.1.weight"]))

        self.eval()

    def forward(self, x):
        """Returns an n_samples x 124928 tensor where each the ith row is the
        LPIPS features of the ith example in [x].
        Args:
        x           -- input to get LPIPS features for with shape B x C x H x W
        normalize   -- whether to normalize the input in 0...1 to -1...1
        """
        x = 2 * x - 1
        
        x = (x - self.shift) / self.scale
        vgg_feats = [normalize_tensor(v) for v in self.vgg(x)]

        feats = [
            torch.multiply(self.lin0, vgg_feats[0]),
            torch.multiply(self.lin1, vgg_feats[1]),
            torch.multiply(self.lin2, vgg_feats[2]),
            torch.multiply(self.lin3, vgg_feats[3]),
            torch.multiply(self.lin4, vgg_feats[4])
        ]

        result = [l.flatten(start_dim=1) for l in feats]
        result = [l / torch.sqrt(torch.tensor(l.shape[-1])) for l in result]
        _, c, h, w = x.shape
        amount_of_res = torch.tensor(c * h * w)
        result += [x.flatten(start_dim=1) * torch.sqrt(self.alpha / amount_of_res)]
        result = torch.cat(result, axis=1)
        return result