import argparse

import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets

from utils import *
from engine import *
from logger import create_logger
from models import *
from helpers import *

from timm.models import create_model

import warnings
warnings.filterwarnings('ignore', 'Argument interpolation should be of type InterpolationMode instead of int')

def get_args_pareser():
    parser = argparse.ArgumentParser(description='ViT')
    # -----------------------------------------------------------------------------
    # Data settings
    # -----------------------------------------------------------------------------
    parser.add_argument('--data_path', type = str, default = '/local_datasets/', help = 'Path of datasets')
    parser.add_argument('--save_path', type = str, default = './checkpoint/', help = 'Path to save model')
    parser.add_argument('--output_path', type = str, default = './output/', help = 'Path to save output')
    parser.add_argument('--sample_path', type = str, default = './sample/', help = 'Path of test samples')
    parser.add_argument('--checkpoint', action="store_true", help = 'Load model from checkpoint or not')
    parser.add_argument('--num_workers', default=4, type=int, help='Number of data loading workers')
    parser.add_argument('--dataset', default='mnist', type=str, help='Dataset name')

    # -----------------------------------------------------------------------------
    # Model settings
    # -----------------------------------------------------------------------------
    parser.add_argument('--model', type = str, default = 'su_vit_tiny_patch16_224', help = 'Model name')
    parser.add_argument('--pretrained', default=True, help='use pre-trained model')
    parser.add_argument('--global_pool', default='token', help='Use CLS token or global pooling')


    # -----------------------------------------------------------------------------
    # Training settings
    # -----------------------------------------------------------------------------
    parser.add_argument('--batch_size', type=int, default=256, 
                        help='The size of batch, this is the total'
                        'batch size of all GPUs on the current node'
                        'when using Data Parallel or Distributed Data Parallel')
    parser.add_argument('--epoch', type=int, default=50, help='The number of epochs to train')
    parser.add_argument('--input_size', type=int, default=224, help='The size of input')
    parser.add_argument('--lr', type=float, default=0.001, help='The learning rate')
    

    # -----------------------------------------------------------------------------
    # Optimizer settings
    # -----------------------------------------------------------------------------
    parser.add_argument('--momentum', type=float, default=0.9, help='The momentum for SGD')
    parser.add_argument('--weight_decay', type=float, default=5e-4, help='The weight decay')


    # -----------------------------------------------------------------------------
    #  Augmentation settings
    # -----------------------------------------------------------------------------
    parser.add_argument('--color-jitter', type=float, default=0.4, metavar='PCT', help='Color jitter factor')
    parser.add_argument('--aa', type=str, default='rand-m9-mstd0.5-inc1', metavar='NAME', help='Use AutoAugment policy'),
    parser.add_argument('--smoothing', type=float, default=0.1, help='Label smoothing')
    parser.add_argument('--interpolation', type=str, default='bicubic', help='Training interpolation (random, bilinear, bicubic)')
    parser.add_argument('--reprob', type=float, default=0.25, metavar='PCT', help='Random erase prob')
    parser.add_argument('--remode', type=str, default='pixel', help='Random erase mode')
    parser.add_argument('--recount', type=int, default=1, help='Random erase count')


    # -----------------------------------------------------------------------------
    #  Misc settings
    # -----------------------------------------------------------------------------
    parser.add_argument('--seed', default=0, type=int, help='Seed for initializing training')
    parser.add_argument('--print_freq', type=int, default=10, help = 'The frequency of printing')
    parser.add_argument('--visualize', action="store_true", default=False, help = 'Whether to visulize the output')
    parser.add_argument('--n_visualize', type=int, default=1, help='Number of images to visualize')
    parser.add_argument('--speed_test', action='store_true', help='Only test speed')
    parser.add_argument('--eval', action='store_true', help='Only evaluate')

    # -----------------------------------------------------------------------------
    #  Selection settings
    # -----------------------------------------------------------------------------
    parser.add_argument('--base_keep_rate', type=float, default=1.0, help='Base keep rate (default: 0.7)')
    parser.add_argument('--drop_loc', default='(3, 6, 9)', type=str, help='the layer indices for shrinking inattentive tokens')

    # -----------------------------------------------------------------------------
    #  Uncertainty settings
    # -----------------------------------------------------------------------------
    parser.add_argument("--uncertainty", action="store_true", help="Use uncertainty or not.")
    parser.add_argument('--uncertainty_keep_rate', type=float, default=0.8, help='Base drop rate (default: 0.8)')
    parser.add_argument("--mse", action="store_true", help="Set this argument when using uncertainty. Sets loss function to Expected Mean Square Error.")
    parser.add_argument("--digamma", action="store_true", help="Set this argument when using uncertainty. Sets loss function to Expected Cross Entropy.")
    parser.add_argument("--log", action="store_true", help="Set this argument when using uncertainty. Sets loss function to Negative Log of the Expected Likelihood.")
    parser.add_argument("--annealing_step", type=int, default=10, help="Set this argument when using uncertainty. Sets the step to start annealing.")


    return parser.parse_args()

def main(args, logger):
    args.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info('[Device]: {}'.format(args.device))

    fix_seed(args.seed)

    train_transform = build_transform(True, args)
    val_transform = build_transform(False, args)

    # Create dataloader
    if args.dataset == 'cifar10':
        train_dataset = datasets.CIFAR10(root=args.data_path, train=True, download=True, transform=train_transform)
        val_dataset = datasets.CIFAR10(root=args.data_path, train=False, download=True, transform=val_transform)
        args.in_chans = 3
    elif args.dataset == 'mnist':
        train_dataset = datasets.MNIST(root=args.data_path, train=True, download=True, transform=train_transform)
        val_dataset = datasets.MNIST(root=args.data_path, train=False, download=True, transform=val_transform)
        args.in_chans = 1
    else:
        raise ValueError("Dataset should be in [cifar10, mnist]")

    args.num_classes = len(train_dataset.classes)
    
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers)
    val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)


    # Create model
    model = create_model(
        args.model,
        base_keep_rate=args.base_keep_rate,
        uncertainty_keep_rate=args.uncertainty_keep_rate,
        drop_loc=eval(args.drop_loc),
        num_classes=args.num_classes,
        global_pool=args.global_pool,
        uncertainty=args.uncertainty,
        in_chans=args.in_chans,
    )
    logger.info('[Model]: \n{}'.format(model))

    if args.speed_test:
        model.load_state_dict(torch.load('{}/vit_mnist_ft.pth'.format(args.save_path))['model_state_dict'])
        model = model.to(args.device)

        inference_speed = speed_test(model, args)
        logger.info('[Inference_speed (inaccurate)]: {:.4f}images/s'.format(inference_speed))
        inference_speed = speed_test(model, args)
        logger.info('[Inference_speed]: {:.4f}images/s'.format(inference_speed))
        inference_speed = speed_test(model, args)
        logger.info('[Inference_speed]: {:.4f}images/s'.format(inference_speed))
        MACs = get_macs(model, args)
        logger.info('[GMACs]: {:.4f}'.format(MACs * 1e-9))

        return
    
    if args.visualize:
        if args.dataset == 'cifar10':
            classes = ['airplane', 'automobile', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck']
        elif args.dataset == 'mnist':
            classes = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
        
        model.load_state_dict(torch.load('{}/vit_mnist_ft.pth'.format(args.save_path))['model_state_dict'])
        model = model.to(args.device)
        
        for i in range(args.n_visualize):
            for c in classes:
                eval_single_image(model, '{}{}/{}.jpg'.format(args.sample_path, c, i), args)
        return
    
    if args.eval:
        model.load_state_dict(torch.load('{}/vit_mnist_ft.pth'.format(args.save_path))['model_state_dict'])
        model = model.to(args.device)

        total_acc = eval_model(model, val_loader, args, logger)

        logger.info('[Total Acc]: {}'.format(total_acc))
        return
    
    if args.checkpoint:
        model.load_state_dict(torch.load('{}/vit_mnist_ft.pth'.format(args.save_path))['model_state_dict'])
        model = model.to(args.device)
    
    model = model.to(args.device)

    # Create optimizer
    optimizer = optim.SGD(model.parameters(), lr = args.lr, momentum=args.momentum, weight_decay=args.weight_decay)

    # Create scheduler
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.1)

    # Create criterion
    if args.uncertainty:
        if args.digamma:
            criterion = edl_digamma_loss
        elif args.log:
            criterion = edl_log_loss
        elif args.mse:
            criterion = edl_mse_loss
    else:
        criterion = nn.CrossEntropyLoss()

    start_time = time.time()

    train_model(model, criterion, train_loader, optimizer, scheduler, args, logger)
    total_acc = eval_model(model, val_loader, args, logger)


    logger.info('[Time Elapsed]: {}'.format(time.strftime("%H:%M:%S", time.gmtime(time.time() - start_time))))

    logger.info('[Total Acc]: {}'.format(total_acc))

    try:
        if not os.path.exists(args.save_path):
            os.makedirs(args.save_path)
    except OSError:
        print ('=> Error: Failed to create directory')
    torch.save({'model_state_dict': model.state_dict()}, args.save_path + 'vit_mnist_ft.pth')

if __name__ == '__main__':
    args = get_args_pareser()

    if not os.path.exists(args.output_path):
        os.makedirs(args.output_path)
    
    logger, file_name = create_logger(args.output_path, args.model)

    with open(os.path.join(args.output_path, file_name), 'a') as f:
        f.write('\n[Arguments]\n{}'.format(str(args)))
    logger.info(f"Full config saved to {os.path.join(args.output_path, file_name)}")
    logger.info('\n[Arguments]\n{}'.format(str(args)))
    
    main(args, logger)