on run
    try
        do shell script "/usr/bin/python3 /Users/sqz/Desktop/git/desktop-launcher.py"
    on error messageText
        display dialog messageText with title "学习教练台 · 启动失败" buttons {"好"} default button "好" with icon caution
    end try
end run
