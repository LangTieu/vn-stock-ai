import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_numerics import (assert_finite_gradients, assert_finite_loss,
                          require_supervised_positions)


class FakeScalar:
    def __init__(self, value):
        self.value = value

    def detach(self):
        return self

    def float(self):
        return self

    def item(self):
        return self.value


class FakeGradient:
    def __init__(self, values):
        self.values = values

    def all(self):
        return FakeScalar(all(math.isfinite(value) for value in self.values))

    def numel(self):
        return len(self.values)


class FakeTorch:
    @staticmethod
    def isfinite(gradient):
        return gradient


class FakeParameter:
    def __init__(self, gradient, requires_grad=True):
        self.grad = gradient
        self.requires_grad = requires_grad


class FakeModel:
    def __init__(self, **parameters):
        self.parameters = parameters

    def named_parameters(self):
        return self.parameters.items()


class NumericalSafetyTests(unittest.TestCase):
    def test_empty_supervised_positions_fail(self):
        with self.assertRaisesRegex(ValueError, 'no supervised target tokens'):
            require_supervised_positions(FakeGradient([]))
        positions = FakeGradient([0])
        self.assertIs(require_supervised_positions(positions), positions)

    def test_finite_loss_passes_unchanged(self):
        loss = FakeScalar(1.25)
        self.assertIs(assert_finite_loss(loss), loss)

    def test_non_finite_loss_fails_before_backward(self):
        with self.assertRaisesRegex(FloatingPointError, 'before backward'):
            assert_finite_loss(FakeScalar(float('nan')))

    def test_finite_trainable_gradients_pass(self):
        model = FakeModel(adapter=FakeParameter(FakeGradient([0.1, -0.2])))
        self.assertEqual(assert_finite_gradients(model, FakeTorch.isfinite, 3), 1)

    def test_non_finite_gradient_names_parameter_and_step(self):
        model = FakeModel(**{'layers.0.lora_A': FakeParameter(FakeGradient([0.1, float('nan')]))})
        with self.assertRaisesRegex(FloatingPointError, 'optimizer step 4: layers.0.lora_A'):
            assert_finite_gradients(model, FakeTorch.isfinite, 4)

    def test_missing_gradients_fail_instead_of_silently_stepping(self):
        model = FakeModel(adapter=FakeParameter(None))
        with self.assertRaisesRegex(RuntimeError, 'No P2a gradients'):
            assert_finite_gradients(model, FakeTorch.isfinite, 1)


if __name__ == '__main__':
    unittest.main()
