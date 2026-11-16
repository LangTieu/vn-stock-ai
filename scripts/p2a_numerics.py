"""Fail fast when P2a loss or optimizer-bound gradients are non-finite."""
import math


def require_supervised_positions(positions):
    if not positions.numel():
        raise ValueError('P2a batch has no supervised target tokens')
    return positions


def assert_finite_loss(loss):
    value = loss.detach().float().item()
    if not math.isfinite(value):
        raise FloatingPointError(f'Non-finite P2a loss before backward: {value}')
    return loss


def assert_finite_gradients(model, isfinite, step):
    checked = 0
    for name, parameter in model.named_parameters():
        gradient = parameter.grad
        if not parameter.requires_grad or gradient is None:
            continue
        checked += 1
        result = isfinite(gradient).all()
        finite = result.item() if hasattr(result, 'item') else result
        if not finite:
            raise FloatingPointError(
                f'Non-finite P2a gradient before optimizer step {step}: {name}')
    if not checked:
        raise RuntimeError(f'No P2a gradients found before optimizer step {step}')
    return checked
