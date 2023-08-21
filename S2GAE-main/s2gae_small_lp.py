import argparse
import os
import torch
from torch.utils.data import DataLoader
from sklearn.metrics import roc_auc_score, average_precision_score
from torch_sparse import SparseTensor
from model import GCN_mgaev3 as GCN
#from model import GCN_mgaev33 as GCN

from model import SAGE_mgaev2 as SAGE
from model import LPDecoder

import os.path as osp
from torch_geometric.datasets import Planetoid
from logger import Logger
from utils import do_edge_split_direct, load_social_graphs, edgemask_um, edgemask_dm
from torch_geometric.utils import to_undirected, add_self_loops, negative_sampling
import numpy as np
import time
import numpy as np
import torch
from torch_geometric.data import Data
from keras.layers import Dense, Input
from keras.models import Model


def DeepAE1(x_train):
    encoding_dim = 256
    input_img = Input(shape=(591,))

    # 编码器层
    encoded = Dense(256, activation='relu')(input_img)
    encoded = Dense(128, activation='relu')(encoded)
    encoder_output = Dense(encoding_dim)(encoded)

    # 解码器层
    decoded = Dense(128, activation='relu')(encoder_output)
    decoded = Dense(256, activation='relu')(decoded)
    decoded = Dense(591, activation='tanh')(decoded)

    # 构建自动编码器模型
    autoencoder = Model(inputs=input_img, outputs=decoded)
    encoder = Model(inputs=input_img, outputs=encoder_output)

    # 编译自动编码器
    autoencoder.compile(optimizer='adam', loss='mse')
    autoencoder.fit(x_train, x_train, epochs=20, batch_size=64, shuffle=True)
    encoded_imgs = encoder.predict(x_train)
    return encoder_output, torch.Tensor(encoded_imgs)


def DeepAE2(x_train):
    encoding_dim = 256
    input_img = Input(shape=(853,))

    # 编码器层
    encoded = Dense(128, activation='relu')(input_img)
    encoded = Dense(64, activation='relu')(encoded)
    encoder_output = Dense(encoding_dim)(encoded)

    # 解码器层
    decoded = Dense(64, activation='relu')(encoder_output)
    decoded = Dense(128, activation='relu')(decoded)
    decoded = Dense(853, activation='tanh')(decoded)

    # 构建自动编码器模型
    autoencoder = Model(inputs=input_img, outputs=decoded)
    encoder = Model(inputs=input_img, outputs=encoder_output)

    # 编译自动编码器
    autoencoder.compile(optimizer='adam', loss='mse')
    autoencoder.fit(x_train, x_train, epochs=20, batch_size=64, shuffle=True)
    encoded_imgs = encoder.predict(x_train)
    return encoder_output, torch.Tensor(encoded_imgs)


def evaluate_auc(train_pred, train_true, val_pred, val_true, test_pred, test_true):
    train_auc = roc_auc_score(train_true, train_pred)
    valid_auc = roc_auc_score(val_true, val_pred)
    test_auc = roc_auc_score(test_true, test_pred)
    train_ap = average_precision_score(train_true, train_pred)
    valid_ap = average_precision_score(val_true, val_pred)
    test_ap = average_precision_score(test_true, test_pred)
    results = dict()
    results['AUC'] = (train_auc, valid_auc, test_auc)
    results['AP'] = (train_ap, valid_ap, test_ap)
    return results


def train(model, predictor, data, split_edge, optimizer, args):
    model.train()
    predictor.train()
    #邻接矩阵adj，边缘索引edge_ndex,和掩码后的边缘索引edge_index_mask
    if args.mask_type == 'um':
        adj, edge_index, edge_index_mask = edgemask_um(args.mask_ratio, split_edge, data.x.device, data.num_nodes)
    else:
        adj, edge_index, edge_index_mask = edgemask_dm(args.mask_ratio, split_edge, data.x.device, data.num_nodes)

    pre_edge_index = adj.to(data.x.device)
    pos_train_edge = edge_index_mask

    optimizer.zero_grad()
    h = model(data.x, pre_edge_index)
    edge = pos_train_edge
    pos_out = predictor(h, edge)
    pos_loss = -torch.log(pos_out + 1e-15).mean()

    # pos_edge = split_edge['train']['edge'].t()
    new_edge_index, _ = add_self_loops(edge_index.cpu())
    edge = negative_sampling(
        new_edge_index, num_nodes=data.num_nodes,
        num_neg_samples=pos_train_edge.shape[1])

    edge = edge.to(data.x.device)

    neg_out = predictor(h, edge)
    neg_loss = -torch.log(1 - neg_out + 1e-15).mean()

    loss = pos_loss + neg_loss
    loss.backward()

    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    torch.nn.utils.clip_grad_norm_(predictor.parameters(), 1.0)

    optimizer.step()

    return loss.item()


@torch.no_grad()
def test(model, predictor, data, adj, split_edge, batch_size):
    model.eval()
    h = model(data.x, adj)

    pos_train_edge = split_edge['train']['edge'].to(data.x.device)
    neg_train_edge = split_edge['train']['edge_neg'].to(data.x.device)
    pos_valid_edge = split_edge['valid']['edge'].to(data.x.device)
    neg_valid_edge = split_edge['valid']['edge_neg'].to(data.x.device)
    pos_test_edge = split_edge['test']['edge'].to(data.x.device)
    neg_test_edge = split_edge['test']['edge_neg'].to(data.x.device)

    pos_train_preds = []
    for perm in DataLoader(range(pos_train_edge.size(0)), batch_size):
        #perm以1024为一组
        edge = pos_train_edge[perm].t()

        pos_train_preds += [predictor(h, edge).squeeze().cpu()]
    pos_train_pred = torch.cat(pos_train_preds, dim=0)

    pos_valid_preds = []
    for perm in DataLoader(range(pos_valid_edge.size(0)), batch_size):
        edge = pos_valid_edge[perm].t()
        pos_valid_preds += [predictor(h, edge).squeeze().cpu()]
    pos_valid_pred = torch.cat(pos_valid_preds, dim=0)

    neg_train_preds = []
    for perm in DataLoader(range(neg_train_edge.size(0)), batch_size):
        edge = neg_train_edge[perm].t()
        neg_train_preds += [predictor(h, edge).squeeze().cpu()]
    neg_train_pred = torch.cat(neg_train_preds, dim=0)

    neg_valid_preds = []
    for perm in DataLoader(range(neg_valid_edge.size(0)), batch_size):
        edge = neg_valid_edge[perm].t()
        neg_valid_preds += [predictor(h, edge).squeeze().cpu()]
    neg_valid_pred = torch.cat(neg_valid_preds, dim=0)

    pos_test_preds = []
    for perm in DataLoader(range(pos_test_edge.size(0)), batch_size):
        edge = pos_test_edge[perm].t()
        pos_test_preds += [predictor(h, edge).squeeze().cpu()]
    pos_test_pred = torch.cat(pos_test_preds, dim=0)

    neg_test_preds = []
    for perm in DataLoader(range(neg_test_edge.size(0)), batch_size):
        edge = neg_test_edge[perm].t()
        neg_test_preds += [predictor(h, edge).squeeze().cpu()]
    neg_test_pred = torch.cat(neg_test_preds, dim=0)

    train_pred = torch.cat([pos_train_pred, neg_train_pred], dim=0)
    train_true = torch.cat([torch.ones_like(pos_train_pred), torch.zeros_like(neg_train_pred)], dim=0)

    val_pred = torch.cat([pos_valid_pred, neg_valid_pred], dim=0)
    val_true = torch.cat([torch.ones_like(pos_valid_pred), torch.zeros_like(neg_valid_pred)], dim=0)

    test_pred = torch.cat([pos_test_pred, neg_test_pred], dim=0)
    test_true = torch.cat([torch.ones_like(pos_test_pred), torch.zeros_like(neg_test_pred)], dim=0)

    results = evaluate_auc(train_pred, train_true, val_pred, val_true, test_pred, test_true)
    return results


def main():
    parser = argparse.ArgumentParser(description='Planetoid (GNN)')
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--use_sage', type=str, default='GCN')
    parser.add_argument('--dataset', type=str, default='CiteSeer')
    parser.add_argument('--mask_type', type=str, default='um', help='um | dm') # whether to use mask features
    parser.add_argument('--de_v', type=str, default='v2', help='v1 | v2') # whether to use mask features
    parser.add_argument('--use_valedges_as_input', action='store_true', default=False)
    parser.add_argument('--num_layers', type=int, default=2)
    parser.add_argument('--decode_layers', type=int, default=2)
    parser.add_argument('--hidden_channels', type=int, default=128)
    parser.add_argument('--decode_channels', type=int, default=256)
    parser.add_argument('--dropout', type=float, default=0.5)
    parser.add_argument('--batch_size', type=int, default=1024)
    parser.add_argument('--lr', type=float, default=0.01)
    parser.add_argument('--epochs', type=int, default=200)
    parser.add_argument('--mask_ratio', type=float, default=0.7)
    parser.add_argument('--eval_steps', type=int, default=1)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--patience', type=int, default=50,
                        help='Use attribute or not')
    parser.add_argument('--seed', type=int, default=42, help='Random seed.')
    args = parser.parse_args()
    print(args)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    device = f'cuda:{args.device}' if torch.cuda.is_available() else 'cpu'
    device = torch.device(device)

    if args.dataset in ['Cora', 'CiteSeer', 'PubMed']:
        # path = osp.join('dataset', args.dataset)
        # dataset = Planetoid(path, args.dataset)
        # data = dataset[0]

        d_ss = np.loadtxt("dataset/AMHMDA/AMHMDA/d_ss.csv", delimiter=',')  # (591, 591)  (263, 312)
        _, d_ss = DeepAE1(d_ss)  # (256, 256)   torch.Size([263, 256])
        m_ss = np.loadtxt("dataset/AMHMDA/AMHMDA/m_ss.csv", delimiter=',')  # (853, 853)  (498, 312)
        _, m_ss = DeepAE2(m_ss)  # (256, 256)   torch.Size([498, 256])
        feature = torch.cat([torch.Tensor(d_ss), torch.Tensor(m_ss)])#(1444,256)   torch.Size([761, 256])
        m_d = np.loadtxt("dataset/AMHMDA/AMHMDA/m_d.csv", delimiter=',')  # (853, 591)   (263, 498)
        adj = []#邻接矩阵
        for m in range(len(m_ss)):#853
            for d in range(len(d_ss)):#591
                if m_d[m][d] == 1:
                    adj.append([d, m])
        adj = torch.LongTensor(adj).T
        print(111,adj)
        data = Data(x=feature, edge_index=adj)#Data(edge_index=[2, 773], x=[761, 256])
    else:
        data = load_social_graphs(args.dataset)
    split_edge = do_edge_split_direct(data)  #对数据集中的边进行划分，主要分为训练集，验证集和测试集


    data.edge_index = to_undirected(split_edge['train']['edge'].t())#将训练集中的有向边转换为无向边
    if args.use_sage == 'GCN':
        # torch.Size([2, 22604])
        edge_index, _ = add_self_loops(data.edge_index)    #add_self_loops是添加自环，edge_index是边缘索引
        adj = SparseTensor.from_edge_index(edge_index).t()#转置
        # SparseTensor(row=tensor([0, 0, 0, ..., 1443, 1443, 1443]),
        #              col=tensor([0, 656, 792, ..., 574, 575, 1443]),
        #              size=(1444, 1444), nnz=22604, density=1.08 %)
    else:
        edge_index = data.edge_index
        adj = SparseTensor.from_edge_index(edge_index).t()
    data = data.to(device)
    adj = adj.to(device)

    save_path_model = 'weight/s2gae-' + args.use_sage + '_{}_{}_{}'.format(args.dataset, args.mask_type, args.de_v) + '_{}'.format(args.num_layers) \
                      + '_hidd{}-{}-{}-{}'.format(args.hidden_channels, args.mask_ratio, args.decode_layers, args.decode_channels) + '_model.pth'
    save_path_predictor = 'weight/s2gae' + args.use_sage + '_{}_{}_{}'.format(args.dataset, args.mask_type, args.de_v) + '_{}'.format(args.num_layers) \
                          + '_hidd{}-{}-{}-{}'.format(args.hidden_channels, args.mask_ratio, args.decode_layers, args.decode_channels) + '_pred.pth'
    print('Start training with mask ratio={} # optimization edges={} / {}'.format(args.mask_ratio,
                                                                                  int(args.mask_ratio *
                                                                                      split_edge['train']['edge'].shape[
                                                                                          0]),
                                                                                  split_edge['train']['edge'].shape[0]))
    metric = 'AUC'
    if args.use_sage == 'SAGE':
        model = SAGE(data.num_features, args.hidden_channels,
                     args.hidden_channels, args.num_layers,
                     args.dropout).to(device)
    else:
        model = GCN(data.num_features, args.hidden_channels,
                    args.hidden_channels, args.num_layers,
                    args.dropout).to(device)
    # args.num_layers：表示 GCN 模型的层数。
    # args.dropout：表示用于防止过拟合的丢弃概率。
    predictor = LPDecoder(args.hidden_channels, args.decode_channels, 1, args.num_layers,
                              args.decode_layers, args.dropout, de_v=args.de_v).to(device)


    #记录AUC和AP
    loggers = {
        'AUC': Logger(args.runs, args),
        'AP': Logger(args.runs, args)
    }

#重置模型和预测器的参数
    for run in range(args.runs):
        model.reset_parameters()
        predictor.reset_parameters()
        optimizer = torch.optim.Adam(
            list(model.parameters()) + list(predictor.parameters()),
            lr=args.lr)

        best_valid = 0.0
        best_epoch = 0
        cnt_wait = 0
        for epoch in range(1, 1 + args.epochs):
            t1 = time.time()
            loss = train(model, predictor, data, split_edge, optimizer,args)
            t2 = time.time()

            results = test(model, predictor, data, adj, split_edge,
                           args.batch_size)

            valid_hits = results[metric][1]
            if valid_hits > best_valid:
                best_valid = valid_hits
                best_epoch = epoch
                torch.save(model.state_dict(), save_path_model)#下载最佳模型的参数到save_path_model路径
                torch.save(predictor.state_dict(), save_path_predictor)#下载最佳预测器的参数到save_path_predictor路径
                cnt_wait = 0
            else:
                cnt_wait += 1

            for key, result in results.items():
                train_hits, valid_hits, test_hits = result

                print(key)
                print(f'Run: {run + 1:02d} / {args.runs:02d}, '
                      f'Epoch: {epoch:02d} / {args.epochs+1:02d}, '
                      f'Best_epoch: {best_epoch:02d}, '
                      f'Best_valid: {100 * best_valid:.2f}%, '
                      f'Loss: {loss:.4f}, '
                      f'Train: {100 * train_hits:.2f}%, '
                      f'Valid: {100 * valid_hits:.2f}%, '
                      f'Test: {100 * test_hits:.2f}%',
                      f'Time: {t2-t1:.2f}%')
            print('***************')
            if cnt_wait == args.patience:
                print('Early stopping!')
                break
        print('##### Testing on {}/{}'.format(run, args.runs))

        model.load_state_dict(torch.load(save_path_model))
        predictor.load_state_dict(torch.load(save_path_predictor))
        results = test(model, predictor, data, adj, split_edge,
                       args.batch_size)

        for key, result in results.items():
            train_hits, valid_hits, test_hits = result
            print(key)
            print(f'**** Testing on Run: {run + 1:02d}, '
                  f'Epoch: {best_epoch:02d}, '
                  f'Train: {100 * train_hits:.2f}%, '
                  f'Valid: {100 * valid_hits:.2f}%, '
                  f'Test: {100 * test_hits:.2f}%')

        for key, result in results.items():
            loggers[key].add_result(run, result)
    if os.path.exists(save_path_model):
        os.remove(save_path_model)
        os.remove(save_path_predictor)
        print('Successfully delete the saved models')
    print('##### Final Testing result')
    for key in loggers.keys():
        print(key)
        loggers[key].print_statistics()


if __name__ == "__main__":
    main()

