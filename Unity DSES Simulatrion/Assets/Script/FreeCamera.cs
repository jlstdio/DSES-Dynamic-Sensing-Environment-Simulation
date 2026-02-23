using UnityEngine;
using UnityEngine.InputSystem; // 최신 입력 시스템 라이브러리 호출

public class FreeCamera : MonoBehaviour
{
    public float moveSpeed = 20f;
    public float lookSpeed = 0.2f; // 마우스 민감도 (신형은 값이 달라서 줄였습니다)
    public float sprintMultiplier = 3f;

    private float rotationX = 0f;
    private float rotationY = 0f;

    void Start()
    {
        // 시작 시점의 카메라 각도 저장
        Vector3 rot = transform.localRotation.eulerAngles;
        rotationX = rot.x;
        rotationY = rot.y;
    }

    void Update()
    {
        // 마우스나 키보드가 연결되어 있지 않으면 무시
        if (Mouse.current == null || Keyboard.current == null) return;

        // 1. 마우스 우클릭을 누르고 있을 때만 시점 회전
        if (Mouse.current.rightButton.isPressed)
        {
            Vector2 mouseDelta = Mouse.current.delta.ReadValue();
            rotationY += mouseDelta.x * lookSpeed;
            rotationX -= mouseDelta.y * lookSpeed;
            
            // 고개 위아래로 꺾이는 각도 제한
            rotationX = Mathf.Clamp(rotationX, -90f, 90f);
            transform.localRotation = Quaternion.Euler(rotationX, rotationY, 0);
        }

        // 2. WASD 및 Q/E 이동 (바라보는 방향 기준)
        float currentSpeed = moveSpeed;
        if (Keyboard.current.leftShiftKey.isPressed) currentSpeed *= sprintMultiplier;

        Vector3 move = Vector3.zero;
        if (Keyboard.current.wKey.isPressed) move += Vector3.forward; // 앞 (W)
        if (Keyboard.current.sKey.isPressed) move += Vector3.back;    // 뒤 (S)
        if (Keyboard.current.aKey.isPressed) move += Vector3.left;    // 좌 (A)
        if (Keyboard.current.dKey.isPressed) move += Vector3.right;   // 우 (D)
        
        if (Keyboard.current.eKey.isPressed) move += Vector3.up;      // 위로 상승 (E)
        if (Keyboard.current.qKey.isPressed) move += Vector3.down;    // 아래로 하강 (Q)

        // 카메라가 바라보는 방향(Space.Self)을 기준으로 이동 적용
        transform.Translate(move.normalized * currentSpeed * Time.deltaTime, Space.Self);
    }
}