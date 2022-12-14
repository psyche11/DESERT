from typing import Optional
import torch
from torch import Tensor
import torch
import torch.nn as nn

from bycha.modules.decoders.layers import AbstractDecoderLayer
from bycha.modules.layers.moe import MoE


class MoEDecoderLayer(AbstractDecoderLayer):
    """
    TransformerDecoderLayer performs one layer of time-masked transformer operation,
    namely self-attention and feed-forward network.

    Args:
        d_model: feature dimension
        nhead: head numbers of multihead attention
        dim_feedforward: dimensionality of inner vector space
        dropout: dropout rate
        activation: activation function used in feed-forward network
        normalize_before: use pre-norm fashion, default as post-norm.
            Pre-norm suit deep nets while post-norm achieve better results when nets are shallow.
    """

    def __init__(self,
                 d_model,
                 nhead,
                 dim_feedforward=2048,
                 dropout=0.1,
                 attention_dropout=0.,
                 activation="relu",
                 normalize_before=False,
                 num_experts=1,
                 sparse=True,):
        super(MoEDecoderLayer, self).__init__()
        self.normalize_before = normalize_before
        self.self_attn = nn.MultiheadAttention(d_model, nhead, dropout=attention_dropout)
        self.multihead_attn = nn.MultiheadAttention(d_model, nhead)
        
        self.moe = MoE(d_model, dim_feedforward=dim_feedforward, activation=activation, 
                       num_experts=num_experts, sparse=sparse)

        self.self_attn_norm = nn.LayerNorm(d_model)
        self.multihead_attn_norm = nn.LayerNorm(d_model)
        self.ffn_norm = nn.LayerNorm(d_model)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.dropout3 = nn.Dropout(dropout)

    def forward(self, tgt: Tensor, memory: Tensor, tgt_mask: Optional[Tensor] = None, memory_mask: Optional[Tensor] = None,
                tgt_key_padding_mask: Optional[Tensor] = None, memory_key_padding_mask: Optional[Tensor] = None):
        r"""
        Pass the inputs (and mask) through the decoder layer in training mode.

        Args:
            tgt: the sequence to the decoder layer (required).
                :math:`(T, B, D)`, where T is sequence length, B is batch size and D is feature dimension
            memory: the sequence from the last layer of the encoder (required).
                :math:`(M, B, D)`, where M is memory size, B is batch size and D is feature dimension
            tgt_mask: the mask for the tgt sequence (optional).
                :math:`(T, T)`, where T is sequence length.
            memory_mask: the mask for the memory sequence (optional).
                :math:`(M, M)`, where M is memory size.
            tgt_key_padding_mask: the mask for the tgt keys per batch (optional).
                :math: `(B, T)`, where B is batch size and T is sequence length.
            memory_key_padding_mask: the mask for the memory keys per batch (optional).
                :math: `(B, M)`, where B is batch size and M is memory size.
        """
        if self._mode == 'infer':
            tgt = tgt[-1:]
            tgt_mask, tgt_key_padding_mask = None, None
        residual = tgt
        if self.normalize_before:
            tgt = self.self_attn_norm(tgt)
        prevs = self._update_cache(tgt) if self._mode == 'infer' else tgt
        tgt = self.self_attn(tgt, prevs, prevs, attn_mask=tgt_mask,
                             key_padding_mask=tgt_key_padding_mask)[0]
        tgt = self.dropout1(tgt)
        tgt = residual + tgt
        if not self.normalize_before:
            tgt = self.self_attn_norm(tgt)

        residual = tgt
        if self.normalize_before:
            tgt = self.multihead_attn_norm(tgt)
        tgt = self.multihead_attn(tgt, memory, memory, attn_mask=memory_mask,
                                  key_padding_mask=memory_key_padding_mask)[0]
        tgt = self.dropout2(tgt)
        tgt = residual + tgt
        if not self.normalize_before:
            tgt = self.multihead_attn_norm(tgt)

        residual = tgt
        if self.normalize_before:
            tgt = self.ffn_norm(tgt)
        tgt, loss = self.moe(tgt)
        tgt = self.dropout3(tgt)
        tgt = residual + tgt
        if not self.normalize_before:
            tgt = self.ffn_norm(tgt)
        return tgt, loss

    def _update_cache(self, cur):
        """
        Update cache with current states

        Args:
            cur: current state
        """
        prev = torch.cat([self._cache['prev'], cur], dim=0) if 'prev' in self._cache else cur
        self._cache['prev'] = prev
        return prev
