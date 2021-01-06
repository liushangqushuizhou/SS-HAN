import os
import torch
import torch.optim as optim
import torch.nn.functional as F
from sklearn.metrics import f1_score
from sklearn.metrics import roc_auc_score

from utils import load_data, EarlyStopping
from sampler import sample

def score(logits, labels):
    _, indices = torch.max(logits, dim=1)
    prediction = indices.long().cpu().numpy()
    labels = labels.cpu().numpy()

    accuracy = (prediction == labels).sum() / len(prediction)
    micro_f1 = f1_score(labels, prediction, average='micro')
    macro_f1 = f1_score(labels, prediction, average='macro')

    return accuracy, micro_f1, macro_f1

def evaluate(model, g, features, labels, mask, loss_func):
    model.eval()
    with torch.no_grad():
        logits = model(g, features)
    loss = loss_func(logits[mask], labels[mask])
    accuracy, micro_f1, macro_f1 = score(logits[mask], labels[mask])

    return loss, accuracy, micro_f1, macro_f1

def get_link_labels(pos_edge_index, neg_edge_index):
    E = pos_edge_index.size(1) + neg_edge_index.size(1)
    link_labels = torch.zeros(E, dtype=torch.float, device=args['device'])
    link_labels[:pos_edge_index.size(1)] = 1.
    return link_labels

def main(args):
    # If args['hetero'] is True, g would be a heterogeneous graph.
    # Otherwise, it will be a list of homogeneous graphs.
    g, features, labels, num_classes, train_idx, val_idx, test_idx, train_mask, \
    val_mask, test_mask = load_data(args['dataset'])

    if hasattr(torch, 'BoolTensor'):
        train_mask = train_mask.bool()
        val_mask = val_mask.bool()
        test_mask = test_mask.bool()

    # features = features.to(args['device'])
    features = [f.to(args['device']) for f in features]
    labels = labels.to(args['device'])
    train_mask = train_mask.to(args['device'])
    val_mask = val_mask.to(args['device'])
    test_mask = test_mask.to(args['device'])

    if args['hetero']:
        from model_hetero import SS_HAN
        model = SS_HAN(muti_meta_paths=
                    [[['pa', 'ap'], ['pf', 'fp']],
                    [['ap', 'pa']],
                    [['fp', 'pf']]],
                    in_size=features[0].shape[1],
                    hidden_size=args['hidden_units'],
                    out_size=num_classes,
                    num_heads=args['num_heads'],
                    dropout=args['dropout']).to(args['device'])

        g = g.to(args['device'])
    else:
        from model import HAN
        model = HAN(num_meta_paths=len(g),
                    in_size=features.shape[1],
                    hidden_size=args['hidden_units'],
                    out_size=num_classes,
                    num_heads=args['num_heads'],
                    dropout=args['dropout']).to(args['device'])
        g = [graph.to(args['device']) for graph in g]

    stopper = EarlyStopping(patience=args['patience'])
    # loss_fcn = F.binary_cross_entropy_with_logits
    loss_fcn = torch.nn.BCEWithLogitsLoss()
    optimizer = optim.Adam(model.parameters(), lr=args['lr'],
                                 weight_decay=args['weight_decay'])
    # lr_scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.95)

    for epoch in range(args['pretrain_epochs']):
        model.train()

        for idx in range(args['batch_size']):
            embeddings = model(g, features)
            pos_edge_index, neg_edge_index = sample(g, 1)
            link_logits = model.calculate_loss(embeddings, pos_edge_index, neg_edge_index)
            link_labels = get_link_labels(pos_edge_index, neg_edge_index)
            loss = loss_fcn(link_logits, link_labels)
            link_probs = link_logits.sigmoid().detach().numpy()
            acc = roc_auc_score(link_labels, link_probs)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            print('link_labels : {}'.format(link_labels))
            print('link_probs : {}'.format(link_probs))
            print('epoch: {} || batch_size : {} || loss: {} || accuracy: {}'.format(epoch, idx, loss, acc))

        # lr_scheduler.step()


if __name__ == '__main__':
    import argparse

    from utils import setup

    parser = argparse.ArgumentParser('HAN')
    parser.add_argument('-s', '--seed', type=int, default=1,
                        help='Random seed')
    parser.add_argument('-ld', '--log-dir', type=str, default='results',
                        help='Dir for saving training results')
    parser.add_argument('--hetero', default=True,
                        help='Use metapath coalescing with DGL\'s own dataset')
    args = parser.parse_args().__dict__

    args = setup(args)

    main(args)