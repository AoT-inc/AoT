## 업그레이드

페이지\: `[톱니바퀴 아이콘] -> Upgrade`

이미 AoT가 설치되어 있다면 웹 인터페이스의 Upgrade 옵션을 사용하거나(권장) 터미널에서 다음 명령을 실행하여 최신 [AoT 릴리스](https://github.com/AoT-inc/AoT/releases)로 업그레이드할 수 있습니다. 업그레이드 과정의 로그는 ``/var/log/aot/aotupgrade.log`` 에 생성되며 `[톱니바퀴 아이콘] -> AoT Logs` 페이지에서도 확인할 수 있습니다.

```bash
sudo aot-commands upgrade-aot
```

## 백업 / 복원 { #backup-restore }

페이지\: `[톱니바퀴 아이콘] -> Backup Restore`

시스템이 업그레이드되거나 웹 인터페이스의 ``[톱니바퀴 아이콘] -> Backup Restore`` 페이지에서 지시를 받으면 /var/AoT-backups 에 백업이 생성됩니다.

백업을 복원해야 하는 경우 ``[톱니바퀴 아이콘] -> Backup  Restore`` 페이지에서 복원할 수 있습니다(권장). 복원하려는 백업을 찾아 그 옆의 Restore 버튼을 누르세요. 웹 인터페이스에 접근할 수 없는 경우 명령줄을 통해서도 복원을 시작할 수 있습니다. 다음 명령을 사용하여 복원을 시작하세요. \[backup_location\] 에는 복원할 백업의 전체 경로를 입력해야 합니다(예: 따옴표 없이 "/var/AoT-backups/AoT-backup-2018-03-11\_21-19-15-5.6.4/").

```bash
sudo aot-commands backup-restore [backup_location]
```
