import QtQuick
import QtQuick.Shapes

// 细圆环加载指示：直径 32，海棠红
// 只在可见时旋转：无限动画会让窗口按显示器刷新率持续重绘，拖动窗口时掉帧。
Item {
    id: ring
    width: 32
    height: 32

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: Theme.color.crabapple
            strokeWidth: 3
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc { centerX: 16; centerY: 16; radiusX: 14; radiusY: 14; startAngle: 0; sweepAngle: 270 }
        }
        RotationAnimator on rotation {
            from: 0; to: 360
            duration: 900
            loops: Animation.Infinite
            running: ring.visible     // 不能写 parent.visible：动画对象没有 parent 属性
        }
    }
}
